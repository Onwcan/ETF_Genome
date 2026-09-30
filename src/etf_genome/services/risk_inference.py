"""Load a saved risk model and score the latest valid feature row.

The desktop window calls this service. It does not call ``model.predict``.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import polars as pl

from etf_genome.config.paths import is_frozen, project_root
from etf_genome.config.settings import AppSettings
from etf_genome.domain.funds import QQQ
from etf_genome.features.risk.dataset import build_risk_dataset


class FeatureSchemaError(ValueError):
    """Raised when a saved model does not match the current feature row."""


@dataclass(frozen=True)
class RiskEstimate:
    fund_id: str
    as_of_date: date | None
    market_data_date: date | None
    holdings_data_date: date | None
    model_id: str | None
    predicted_volatility_20d: float | None
    predicted_max_drawdown_20d: float | None
    tail_event_probability: float | None
    trained_through: date | None
    message: str
    created_at: datetime
    model_version: str | None = None
    feature_family: str | None = None
    dataset_version: str | None = None


def _artifact_root() -> Path:
    """Locate registry files in a source checkout or a frozen onedir bundle."""

    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if isinstance(meipass, str):
            bundled = Path(meipass)
            if (bundled / "models" / "registry" / "registry.json").is_file():
                return bundled
    return project_root()


def risk_model_dir() -> Path:
    """Locate packaged model files without using a machine-specific path."""

    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass is not None:
            bundled = Path(meipass) / "models" / "risk_baseline"
            if bundled.is_dir():
                return bundled
    return project_root() / "models" / "risk_baseline"


def estimate_qqq_risk(
    settings: AppSettings,
    model_dir: Path | None = None,
) -> RiskEstimate:
    """Score QQQ from local data. Missing models or prices stay null."""

    created = datetime.now(UTC)
    directory = model_dir or risk_model_dir()
    try:
        dataset, _meta = build_risk_dataset(settings)
    except Exception:
        if not _models_present(directory, "qqq_market"):
            return _empty(created, "Risk baseline model has not been trained.")
        return _empty(created, "Market data unavailable.")
    usable = dataset.filter(pl.col("return_1d").is_not_null()).sort("trading_date")
    if usable.is_empty():
        return _empty(created, "Market data unavailable.")
    row = usable.row(-1, named=True)
    family = "genome" if row.get("holding_count") is not None else "market"
    legacy = "qqq_genome" if family == "genome" else "qqq_market"
    use_registry = model_dir is None
    vol_path, vol_record = _resolve_model(
        directory,
        legacy,
        "volatility",
        "forward_realized_vol_20d",
        family,
        use_registry=use_registry,
    )
    dd_path, _drawdown_record = _resolve_model(
        directory,
        legacy,
        "drawdown",
        "forward_max_drawdown_20d",
        family,
        use_registry=use_registry,
    )
    if not vol_path.is_file() or not dd_path.is_file():
        return _empty(created, "Risk baseline model has not been trained.")
    tail_path, _tail_record = _resolve_model(
        directory,
        legacy,
        "tail",
        "tail_event_20d",
        family,
        use_registry=use_registry,
    )
    try:
        volatility, trained = _predict(vol_path, row)
        drawdown, _trained = _predict(dd_path, row)
        tail_probability = _predict(tail_path, row)[0] if tail_path.is_file() else None
    except FeatureSchemaError:
        return _empty(created, "Risk model feature schema is incompatible.")
    except Exception as exc:
        if os.environ.get("ETF_GENOME_RISK_DEBUG") == "1":
            detail = str(exc).replace("\n", " ")
            leaf = detail.split("\\")[-1].split("/")[-1][:160]
            print(f"RISK_RUNTIME:{type(exc).__name__}:{leaf}", file=sys.stderr)
        return _empty(created, "Risk model runtime is unavailable.")
    holdings_date = row.get("report_date")
    model_id = vol_path.stem if vol_record is None else vol_record.model_id
    return RiskEstimate(
        fund_id=QQQ.fund_id,
        as_of_date=row["trading_date"],
        market_data_date=row["trading_date"],
        holdings_data_date=holdings_date if isinstance(holdings_date, date) else None,
        model_id=model_id,
        predicted_volatility_20d=volatility,
        predicted_max_drawdown_20d=drawdown,
        tail_event_probability=tail_probability,
        trained_through=trained,
        model_version=None if vol_record is None else vol_record.model_version,
        feature_family=family if vol_record is not None else None,
        dataset_version=None if vol_record is None else vol_record.dataset_version,
        message=(
            "Model outputs are research estimates and are not financial advice "
            "or guaranteed forecasts."
        ),
        created_at=created,
    )


def format_risk_estimate(estimate: RiskEstimate) -> str:
    """Format model estimates for the desktop summary."""

    if estimate.predicted_volatility_20d is None or estimate.predicted_max_drawdown_20d is None:
        detail = estimate.message
        if detail == "Market data unavailable.":
            detail = "Market data unavailable"
        return f"Risk Baseline\n{detail}"
    lines = [
        "Risk Baseline",
        "These figures are model estimates, not guaranteed outcomes.",
        f"Market data through: {estimate.market_data_date}",
        f"Estimated forward 20-day volatility: {estimate.predicted_volatility_20d * 100:.1f}%",
        (
            "Estimated forward 20-day max drawdown: "
            f"{estimate.predicted_max_drawdown_20d * 100:.1f}%"
        ),
    ]
    if estimate.tail_event_probability is not None:
        lines.append(f"Tail-event probability: {estimate.tail_event_probability * 100:.1f}%")
    lines.append("Model: XGBoost baseline")
    if estimate.model_version is not None:
        lines.append(f"Model version: {estimate.model_version}")
    if estimate.feature_family is not None:
        lines.append(f"Model feature family: {estimate.feature_family}")
    if estimate.dataset_version is not None:
        lines.append(f"Dataset version: {estimate.dataset_version}")
    if estimate.trained_through is not None:
        lines.append(f"Model trained through: {estimate.trained_through.isoformat()}")
    lines.append(estimate.message)
    return "\n".join(lines)


class _Booster(Protocol):
    def load_model(self, fname: str) -> None: ...

    def predict(self, data: Any) -> Any: ...


class _XGBoostApi(Protocol):
    """Structural view of the native booster API.

    The xgboost package has no ``py.typed`` marker, and the frozen executable
    loads its DLL before import. This protocol is the typed adapter.
    """

    def Booster(self) -> _Booster: ...

    def DMatrix(self, *args: Any, **kwargs: Any) -> Any: ...


def _import_xgboost() -> _XGBoostApi:
    """Import XGBoost, pointing a frozen build at the bundled DLL."""

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and "xgboost" not in sys.modules:
        dll = Path(meipass) / "xgboost" / "lib" / "xgboost.dll"
        if dll.is_file():
            _install_frozen_libpath(dll)
    import xgboost as xgb

    return cast(_XGBoostApi, xgb)


def _install_frozen_libpath(dll: Path) -> None:
    class _Loader(importlib.abc.Loader):
        def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:
            return None

        def exec_module(self, module: object) -> None:
            module.find_lib_path = lambda: [str(dll)]  # type: ignore[attr-defined]
            module.XGBoostLibraryNotFound = RuntimeError  # type: ignore[attr-defined]

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(
            self,
            fullname: str,
            path: object = None,
            target: object = None,
        ) -> importlib.machinery.ModuleSpec | None:
            if fullname != "xgboost.libpath":
                return None
            return importlib.machinery.ModuleSpec(fullname, _Loader())

    sys.meta_path.insert(0, _Finder())


def _predict(path: Path, row: dict[str, object]) -> tuple[float, date | None]:
    xgb = _import_xgboost()

    metadata_path = path.with_name(path.stem + ".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    features = metadata.get("features")
    if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
        raise FeatureSchemaError("Model metadata is missing a feature list.")
    values: list[float] = []
    for feature in features:
        if feature not in row:
            raise FeatureSchemaError(f"Feature {feature} is not in the current row.")
        value = row.get(feature)
        if value is None:
            values.append(np.nan)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FeatureSchemaError(f"Feature {feature} is not numeric.")
        values.append(float(value))
    booster = xgb.Booster()
    booster.load_model(str(path))
    matrix = xgb.DMatrix(
        np.array([values], dtype=np.float64),
        feature_names=[str(feature) for feature in features],
        missing=np.nan,
    )
    prediction = booster.predict(matrix)
    trained = metadata.get("train_end")
    trained_date = date.fromisoformat(trained) if isinstance(trained, str) else None
    return float(prediction[0]), trained_date


def _resolve_model(
    directory: Path,
    legacy_family: str,
    short_name: str,
    target: str,
    feature_family: str,
    *,
    use_registry: bool,
) -> tuple[Path, Any]:
    from etf_genome.domain.funds import QQQ as _qqq
    from etf_genome.experiments.registry import ModelRegistryService

    if use_registry:
        record = ModelRegistryService(_artifact_root()).get_production_model(
            _qqq.fund_id, target, feature_family
        )
        if record is not None:
            promoted = _artifact_root() / record.artifact
            if promoted.is_file():
                return promoted, record
    return directory / f"{legacy_family}_{short_name}_20d_xgb.json", None


def _models_present(directory: Path, family: str) -> bool:
    return (directory / f"{family}_volatility_20d_xgb.json").is_file()


def _empty(created: datetime, message: str) -> RiskEstimate:
    return RiskEstimate(
        fund_id=QQQ.fund_id,
        as_of_date=None,
        market_data_date=None,
        holdings_data_date=None,
        model_id=None,
        predicted_volatility_20d=None,
        predicted_max_drawdown_20d=None,
        tail_event_probability=None,
        trained_through=None,
        message=message,
        created_at=created,
    )
