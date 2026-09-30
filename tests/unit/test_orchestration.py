"""Orchestration tests. They do not start Airflow, Kubernetes, or Docker."""

from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.orchestration import graphs, publish, tasks, training_flow
from etf_genome.orchestration.publish import DatasetNotReady


def test_failed_validation_keeps_the_previous_dataset(tmp_path: Path) -> None:
    live = tmp_path / "qqq_risk_dataset.parquet"
    live.write_bytes(b"previous-good-dataset")
    with pytest.raises(DatasetNotReady):
        publish.publish_prepared(tmp_path, _frame(leaked=True), _timeline(), _meta())
    assert live.read_bytes() == b"previous-good-dataset"
    assert not (tmp_path / "dataset_ready.json").exists()


def test_publish_is_atomic_and_idempotent(tmp_path: Path) -> None:
    first = publish.publish_prepared(tmp_path, _frame(leaked=False), _timeline(), _meta())
    second = publish.publish_prepared(tmp_path, _frame(leaked=False), _timeline(), _meta())
    assert first["validation_status"] == "PASSED"
    assert first["fingerprint"] == "a" * 64
    assert second["row_count"] == 1
    stored = pl.read_parquet(tmp_path / "qqq_risk_dataset.parquet")
    assert stored.height == 1
    manifest = json.loads((tmp_path / "dataset_ready.json").read_text(encoding="utf-8"))
    publish.require_fingerprint(manifest, "a" * 64)
    with pytest.raises(DatasetNotReady):
        publish.require_fingerprint(manifest, "b" * 64)


def test_duplicate_market_sessions_are_rejected() -> None:
    frame = pl.DataFrame(
        {
            "trading_date": [date(2024, 1, 2), date(2024, 1, 2)],
            "provider": ["twelvedata", "twelvedata"],
        }
    )
    with pytest.raises(DatasetNotReady):
        tasks.validate_canonical_bars(frame)


def test_candidate_flow_does_not_promote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: AppSettings,
) -> None:
    fingerprint = "c" * 64
    directory = tmp_path / "models" / "experiments" / "m" / "1"
    directory.mkdir(parents=True)
    (directory / "model.metadata.json").write_text("{}", encoding="utf-8")

    def _load(_settings: object) -> tuple[None, dict[str, str]]:
        return None, {"fingerprint": fingerprint}

    def _train(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "dataset_fingerprint": fingerprint,
            "model_id": "m",
            "model_version": "1",
            "metrics": {"validation": {"mae": 0.1}, "test": {"mae": 0.2}},
            "seed": 42,
        }

    class _Record:
        state = "CANDIDATE"
        model_id = "m"
        model_version = "1"
        target = "forward_realized_vol_20d"
        feature_family = "market"
        dataset_fingerprint = fingerprint
        mlflow_run = None

    monkeypatch.setattr(training_flow, "load_dataset", _load)
    monkeypatch.setattr(training_flow, "train_best", _train)
    monkeypatch.setattr(training_flow, "register_trained_model", lambda _root, _path: _Record())
    report = training_flow.train_candidate(
        settings=settings,
        study_name="qqq-volatility-20d-market",
        expected_fingerprint=fingerprint,
        root=tmp_path,
    )
    assert report["state"] == "CANDIDATE"
    assert "promote(" not in inspect.getsource(training_flow)
    tracked = training_flow.log_tracking(
        tmp_path,
        tracking_mode="none",
        run_name="unit",
        metrics={"validation_mae": 0.1},
    )
    assert tracked["wandb_mode"] == "disabled"


def test_fingerprint_mismatch_stops_before_training(
    monkeypatch: pytest.MonkeyPatch,
    settings: AppSettings,
) -> None:
    monkeypatch.setattr(
        training_flow,
        "load_dataset",
        lambda _settings: (None, {"fingerprint": "d" * 64}),
    )

    def _forbidden(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("training started on the wrong dataset")

    monkeypatch.setattr(training_flow, "train_best", _forbidden)
    with pytest.raises(training_flow.DatasetFingerprintError):
        training_flow.train_candidate(
            settings=settings,
            study_name="qqq-volatility-20d-market",
            expected_fingerprint="e" * 64,
        )


def test_dag_contracts_reuse_services_and_do_not_promote() -> None:
    assert [dag.dag_id for dag in graphs.DAGS] == [
        "etf_genome_market_sync",
        "etf_genome_sec_sync",
        "etf_genome_risk_dataset",
    ]
    for dag in graphs.DAGS:
        assert dag.catchup is False
        assert dag.retries == 1
        assert dag.schedule is None
        assert len(dag.task_ids()) == len(set(dag.task_ids()))
    assert graphs.MARKET_SYNC.tasks[-1].upstream == ("verify_provenance",)
    source = inspect.getsource(tasks)
    assert "sync_qqq_market" in source
    assert "build_update_coordinator" in source
    assert "publish_risk_dataset" in source
    assert "promote(" not in source
    pipeline = Path("orchestration/kubeflow/qqq_risk_pipeline.py").read_text(encoding="utf-8")
    assert "promote(" not in pipeline
    assert "etf_genome_qqq_risk_training" in pipeline


def _frame(*, leaked: bool) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trading_date": [date(2024, 1, 2)],
            "available_from": [date(2024, 1, 3 if leaked else 1)],
            "holding_count": [10],
            "split": ["train"],
            "close": [1.0],
        }
    )


def _timeline() -> pl.DataFrame:
    return pl.DataFrame(schema={"publication_date": pl.Date})


def _meta() -> dict[str, object]:
    return {
        "fingerprint": "a" * 64,
        "dataset_version": "qqq-risk-1",
        "feature_version": "market-genome-1",
        "target_version": "fwd-20d-1",
        "provider": ["twelvedata"],
    }
