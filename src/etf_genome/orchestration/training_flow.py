"""Candidate-only training flow. This module never promotes a model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import xgboost

from etf_genome.config.paths import project_root
from etf_genome.config.settings import AppSettings
from etf_genome.experiments.study import (
    DatasetFingerprintError,
    open_study,
    run_study,
    study_storage,
)
from etf_genome.experiments.tracking import ResearchTracker
from etf_genome.experiments.workflow import (
    config_from_path,
    load_dataset,
    register_trained_model,
    train_best,
)
from etf_genome.orchestration.publish import DatasetNotReady, load_manifest, require_fingerprint

try:
    import optuna

    _OPTUNA_VERSION: str | None = optuna.__version__
except ImportError:  # pragma: no cover - optuna is a research extra
    _OPTUNA_VERSION = None


def assert_manifest(path: Path, expected_fingerprint: str) -> dict[str, object]:
    manifest = load_manifest(path)
    require_fingerprint(manifest, expected_fingerprint)
    return manifest


def tune_study(
    settings: AppSettings,
    *,
    study_name: str,
    expected_fingerprint: str,
    root: Path | None = None,
    tracking_mode: str = "none",
) -> dict[str, object]:
    """Resume one existing Optuna study. The test split stays out of the objective."""

    base = root or project_root()
    _frame, meta = load_dataset(settings)
    actual = str(meta["fingerprint"])
    if actual != expected_fingerprint:
        raise DatasetFingerprintError(
            f"Dataset fingerprint {actual} does not match {expected_fingerprint}."
        )
    config = config_from_path()
    spec = config.study(study_name)
    direction: Literal["minimize", "maximize"] = (
        "maximize" if spec.task == "classification" else "minimize"
    )
    study = open_study(
        storage=study_storage(base),
        base_name=spec.study_name,
        fingerprint=actual,
        direction=direction,
        resume=True,
        seed=config.seed,
    )
    run_study(
        study,
        _frame,
        spec,
        n_trials=config.n_trials,
        seed=config.seed,
        nthread=config.nthread,
        round_min=config.num_boost_round_min,
        round_max=config.num_boost_round_max,
    )
    tracked = _track(base, tracking_mode, study_name, {"dataset_fingerprint": actual})
    return {
        "study_name": spec.study_name,
        "dataset_fingerprint": actual,
        "wandb_mode": tracked.wandb_mode,
        "optuna_version": _OPTUNA_VERSION,
        "xgboost_version": xgboost.__version__,
        "seed": config.seed,
    }


def train_candidate(
    settings: AppSettings,
    *,
    study_name: str,
    expected_fingerprint: str,
    root: Path | None = None,
) -> dict[str, object]:
    """Refit the frozen trial, score test once, and register a candidate."""

    base = root or project_root()
    _frame, meta = load_dataset(settings)
    if str(meta["fingerprint"]) != expected_fingerprint:
        raise DatasetFingerprintError("Refusing to train on a different dataset fingerprint.")
    metadata = train_best(settings, config_from_path(), study_name, root=base)
    if str(metadata["dataset_fingerprint"]) != expected_fingerprint:
        raise DatasetNotReady("Frozen model fingerprint drifted from the manifest.")
    metadata_path = (
        base
        / "models"
        / "experiments"
        / str(metadata["model_id"])
        / str(metadata["model_version"])
        / "model.metadata.json"
    )
    record = register_trained_model(base, metadata_path)
    if record.state != "CANDIDATE":
        raise DatasetNotReady(f"Orchestration created state {record.state}.")
    report = {
        "state": record.state,
        "model_id": record.model_id,
        "model_version": record.model_version,
        "target": record.target,
        "feature_family": record.feature_family,
        "dataset_fingerprint": record.dataset_fingerprint,
        "mlflow_run": record.mlflow_run,
        "metrics": metadata.get("metrics"),
        "seed": metadata.get("seed"),
        "xgboost_version": xgboost.__version__,
        "optuna_version": _OPTUNA_VERSION,
    }
    report_path = metadata_path.with_name("candidate_report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def log_tracking(
    root: Path,
    *,
    tracking_mode: str,
    run_name: str,
    metrics: dict[str, float],
) -> dict[str, object]:
    """Log optional research metrics. Disabled mode does not need an API key."""

    result = _track(root, tracking_mode, run_name, {}, metrics)
    return {"wandb_mode": result.wandb_mode, "errors": result.errors, "run_id": result.wandb_run_id}


def _track(
    root: Path,
    tracking_mode: str,
    run_name: str,
    config: dict[str, Any],
    metrics: dict[str, float] | None = None,
) -> Any:
    tracker = ResearchTracker(tracking_mode, root=root, run_name=run_name, config=config)
    tracker.start()
    if metrics:
        tracker.log(metrics)
    return tracker.finish()
