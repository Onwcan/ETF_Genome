"""Small model round-trip tests. They do not fit the historical QQQ baseline."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.market import MarketBar
from etf_genome.data.storage.market_store import MarketStore
from etf_genome.experiments.registry import ModelRegistryService, new_record
from etf_genome.features.market.series import MARKET_FEATURES
from etf_genome.services.risk_inference import FeatureSchemaError, _predict, estimate_qqq_risk
from etf_genome.training import train_risk_baseline as training


def test_training_module_has_no_random_splitter() -> None:
    source = inspect.getsource(training)
    assert "train_test_split" not in source
    assert "KFold" not in source


def test_xgboost_seed_and_round_trip(tmp_path: Path) -> None:
    import xgboost as xgb

    features = np.arange(40, dtype=float).reshape(20, 2)
    target = features[:, 0] * 0.01
    params = {
        "max_depth": 2,
        "eta": 0.1,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "seed": 42,
        "nthread": 1,
        "objective": "reg:squarederror",
    }
    first = xgb.train(params, xgb.DMatrix(features, label=target), num_boost_round=8)
    second = xgb.train(params, xgb.DMatrix(features, label=target), num_boost_round=8)
    probe = xgb.DMatrix(features[:1])
    assert first.predict(probe) == pytest.approx(second.predict(probe))
    path = tmp_path / "model.json"
    first.save_model(path)
    loaded = xgb.Booster()
    loaded.load_model(path)
    assert loaded.predict(probe) == pytest.approx(first.predict(probe))


def test_inference_accepts_a_matching_row_and_rejects_a_bad_schema(
    settings: AppSettings,
) -> None:
    directory = settings.resolved_data_dir / "models"
    directory.mkdir()
    _save_market_models(directory)
    _save_bars(settings)
    estimate = estimate_qqq_risk(settings, directory)
    assert estimate.model_id == "qqq_market_volatility_20d_xgb"
    assert estimate.predicted_volatility_20d is not None
    assert estimate.predicted_max_drawdown_20d is not None
    assert estimate.tail_event_probability is None
    assert estimate.market_data_date == date(2024, 1, 10)

    broken = directory / "qqq_market_volatility_20d_xgb.metadata.json"
    payload = json.loads(broken.read_text(encoding="utf-8"))
    payload["features"] = [*MARKET_FEATURES, "not_a_feature"]
    broken.write_text(json.dumps(payload), encoding="utf-8")
    row = {feature: 0.1 for feature in MARKET_FEATURES}
    with pytest.raises(FeatureSchemaError):
        _predict(directory / "qqq_market_volatility_20d_xgb.json", row)
    rejected = estimate_qqq_risk(settings, directory)
    assert rejected.predicted_volatility_20d is None
    assert "incompatible" in rejected.message


def test_missing_model_does_not_invent_a_forecast(settings: AppSettings) -> None:
    estimate = estimate_qqq_risk(settings, settings.resolved_data_dir / "missing-models")
    assert estimate.predicted_volatility_20d is None
    assert "not been trained" in estimate.message


def test_promoted_model_is_used_and_a_newer_candidate_is_not(
    settings: AppSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "etf_genome.services.risk_inference.project_root",
        lambda: tmp_path,
    )
    _save_bars(settings)
    fallback = tmp_path / "models" / "risk_baseline"
    fallback.mkdir(parents=True)
    _save_market_models(fallback)
    first = _registry_model(tmp_path / "v1", "1")
    second = _registry_model(tmp_path / "v2", "2")
    registry = ModelRegistryService(tmp_path)
    registry.register_candidate(*first)
    registry.promote("qqq_market_volatility_xgb", "1")
    registry.register_candidate(*second)
    estimate = estimate_qqq_risk(settings)
    assert estimate.model_id == "qqq_market_volatility_xgb"
    assert estimate.model_version == "1"
    assert estimate.feature_family == "market"
    assert estimate.dataset_version == "qqq-risk-1"
    assert estimate.predicted_volatility_20d is not None


def _registry_model(directory: Path, version: str):
    import xgboost as xgb

    directory.mkdir(parents=True)
    features = np.zeros((30, len(MARKET_FEATURES)))
    booster = xgb.train(
        {
            "max_depth": 2,
            "eta": 0.3,
            "seed": 42,
            "nthread": 1,
            "objective": "reg:squarederror",
        },
        xgb.DMatrix(features, label=np.full(30, 0.2), feature_names=list(MARKET_FEATURES)),
        num_boost_round=4,
    )
    model = directory / "model.json"
    meta = directory / "model.metadata.json"
    booster.save_model(model)
    meta.write_text(
        json.dumps(
            {
                "features": MARKET_FEATURES,
                "target": "forward_realized_vol_20d",
                "train_end": "2023-12-31",
            }
        ),
        encoding="utf-8",
    )
    record = new_record(
        model_id="qqq_market_volatility_xgb",
        model_version=version,
        target="forward_realized_vol_20d",
        feature_family="market",
        dataset_fingerprint="a" * 64,
        dataset_version="qqq-risk-1",
        feature_version="market-genome-1",
        target_version="fwd-20d-1",
        artifact="",
        train_end="2023-12-31",
        validation_end="2024-12-31",
        metrics={"validation": {"mae": 0.1}, "test": {"mae": 0.2}},
    )
    return record, model, meta


def _save_market_models(directory: Path) -> None:
    import xgboost as xgb

    folder = directory
    features = np.zeros((30, len(MARKET_FEATURES)))
    for name, level in (
        ("qqq_market_volatility_20d_xgb", 0.2),
        ("qqq_market_drawdown_20d_xgb", 0.05),
    ):
        booster = xgb.train(
            {
                "max_depth": 2,
                "eta": 0.3,
                "seed": 42,
                "nthread": 1,
                "objective": "reg:squarederror",
            },
            xgb.DMatrix(features, label=np.full(30, level)),
            num_boost_round=4,
        )
        path = folder / f"{name}.json"
        booster.save_model(path)
        path.with_name(path.stem + ".metadata.json").write_text(
            json.dumps(
                {
                    "model_id": name,
                    "features": MARKET_FEATURES,
                    "train_end": "2023-12-31",
                }
            ),
            encoding="utf-8",
        )


def _save_bars(settings: AppSettings) -> None:
    bars = [
        MarketBar(
            instrument_id="ticker:QQQ",
            ticker="QQQ",
            trading_date=date(2024, 1, index),
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.0 + index,
            volume=1_000.0,
            currency="USD",
            exchange="NASDAQ",
            provider="twelvedata",
            adjustment_mode="all",
            downloaded_at=datetime(2024, 1, 10, tzinfo=UTC),
        )
        for index in range(2, 11)
    ]
    MarketStore(settings).upsert(bars)
