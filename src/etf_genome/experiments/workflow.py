"""Research commands. The desktop application does not import this module."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import polars as pl

from etf_genome.config.paths import project_root
from etf_genome.config.settings import AppSettings
from etf_genome.experiments.booster import (
    average_precision,
    matrices,
    predict,
    regression_scores,
)
from etf_genome.experiments.config import ExperimentFile, StudySpec, load_experiment_file
from etf_genome.experiments.registry import ModelRecord, ModelRegistryService, new_record
from etf_genome.experiments.study import (
    best_complete_trial,
    open_study,
    refit_best,
    run_study,
    study_storage,
    trial_counts,
)
from etf_genome.experiments.tracking import ResearchTracker
from etf_genome.features.risk.dataset import DATASET_VERSION, FEATURE_VERSION, TARGET_VERSION


def default_config_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "configs" / "experiments" / "qqq_risk_baseline.toml"


def load_dataset(settings: AppSettings) -> tuple[pl.DataFrame, dict[str, Any]]:
    path = settings.processed_dir / "features" / "qqq_risk_dataset.parquet"
    meta_path = settings.processed_dir / "features" / "qqq_risk_dataset_meta.json"
    frame = pl.read_parquet(path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return frame, meta


def tune(
    settings: AppSettings,
    config: ExperimentFile,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    base = root or project_root()
    frame, meta = load_dataset(settings)
    fingerprint = str(meta["fingerprint"])
    storage = study_storage(base)
    summaries: list[dict[str, Any]] = []
    for spec in config.studies:
        direction: Literal["minimize", "maximize"] = (
            "maximize" if spec.task == "classification" else "minimize"
        )
        study = open_study(
            storage=storage,
            base_name=spec.study_name,
            fingerprint=fingerprint,
            direction=direction,
            resume=True,
            seed=config.seed,
        )
        run_study(
            study,
            frame,
            spec,
            n_trials=config.n_trials,
            seed=config.seed,
            nthread=config.nthread,
            round_min=config.num_boost_round_min,
            round_max=config.num_boost_round_max,
        )
        counts = trial_counts(study)
        best = best_complete_trial(study) if counts["complete"] else None
        tracker = ResearchTracker(
            config.tracking,
            root=base,
            run_name=f"{spec.study_name}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
            config={
                "experiment_id": spec.experiment_id,
                "target": spec.target,
                "feature_family": spec.feature_family,
                "dataset_fingerprint": fingerprint,
                "seed": config.seed,
            },
        )
        tracker.start()
        if best is not None and best.value is not None:
            metric_name = "validation_mae"
            if spec.task == "classification":
                metric_name = "validation_pr_auc"
            tracker.log({metric_name: float(best.value)})
        tracked = tracker.finish()
        summaries.append(
            {
                "study": study.study_name,
                "experiment_id": spec.experiment_id,
                "target": spec.target,
                "feature_family": spec.feature_family,
                "dataset_fingerprint": fingerprint,
                "counts": counts,
                "best_value": None if best is None else best.value,
                "best_params": None if best is None else best.params,
                "wandb_mode": tracked.wandb_mode,
                "wandb_run": tracked.wandb_run_id,
                "tracking_errors": tracked.errors,
            }
        )
    report = {
        "dataset_fingerprint": fingerprint,
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "target_version": TARGET_VERSION,
        "studies": summaries,
    }
    directory = base / "reports" / "experiments"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "optuna_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def train_best(
    settings: AppSettings,
    config: ExperimentFile,
    study_name: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Refit the best validation trial, then score the untouched test split once."""

    base = root or project_root()
    frame, meta = load_dataset(settings)
    fingerprint = str(meta["fingerprint"])
    spec = config.study(study_name)
    direction: Literal["minimize", "maximize"] = (
        "maximize" if spec.task == "classification" else "minimize"
    )
    study = open_study(
        storage=study_storage(base),
        base_name=spec.study_name,
        fingerprint=fingerprint,
        direction=direction,
        resume=True,
        seed=config.seed,
    )
    best = best_complete_trial(study)
    params = dict(best.params)
    rounds = int(params.pop("num_boost_round"))
    native = _native_params(params, spec.task, config.seed, config.nthread)
    booster = refit_best(frame, spec, native, rounds)
    features = spec.features()
    if spec.feature_family == "market":
        usable = frame
    else:
        usable = frame.filter(pl.col("holding_count").is_not_null())
    metrics: dict[str, Any] = {}
    for split in ("validation", "test"):
        if split == "test":
            x_split, y_split = _test_matrices(usable, features, spec.target)
        else:
            x_split, y_split = matrices(usable, features, spec.target, "validation")
        scores = predict(booster, x_split, features)
        if spec.task == "classification":
            metrics[split] = {"pr_auc": average_precision(y_split, scores)}
        else:
            metrics[split] = regression_scores(y_split, scores)
    model_id = f"qqq_{spec.feature_family}_{_short(spec.target)}_xgb"
    version = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = base / "models" / "experiments" / model_id / version
    directory.mkdir(parents=True, exist_ok=True)
    booster.save_model(directory / "model.json")
    metadata = {
        "model_id": model_id,
        "model_version": version,
        "model_type": "xgboost.Booster",
        "target": spec.target,
        "feature_family": spec.feature_family,
        "features": features,
        "dataset_fingerprint": fingerprint,
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "target_version": TARGET_VERSION,
        "train_end": config.train_end.isoformat(),
        "validation_end": config.validation_end.isoformat(),
        "optuna_study": study.study_name,
        "metrics": metrics,
        "parameters": best.params,
        "seed": config.seed,
    }
    (directory / "model.metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    mlflow_run = _log_mlflow(base, spec, metadata, directory / "model.json")
    metadata["mlflow_run"] = mlflow_run
    (directory / "model.metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def register_trained_model(root: Path, metadata_path: Path) -> ModelRecord:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    model_path = metadata_path.with_name("model.json")
    record = new_record(
        model_id=str(metadata["model_id"]),
        model_version=str(metadata["model_version"]),
        state="CANDIDATE",
        target=str(metadata["target"]),
        feature_family=str(metadata["feature_family"]),
        dataset_fingerprint=str(metadata["dataset_fingerprint"]),
        dataset_version=str(metadata["dataset_version"]),
        feature_version=str(metadata["feature_version"]),
        target_version=str(metadata["target_version"]),
        artifact="",
        train_end=str(metadata["train_end"]),
        validation_end=str(metadata["validation_end"]),
        optuna_study=metadata.get("optuna_study"),
        wandb_run=metadata.get("wandb_run"),
        mlflow_run=metadata.get("mlflow_run"),
        metrics=metadata.get("metrics"),
    )
    return ModelRegistryService(root).register_candidate(record, model_path, metadata_path)


def _test_matrices(frame: pl.DataFrame, features: list[str], target: str) -> tuple[Any, Any]:
    """Score test only from the frozen-model command, never from Optuna."""

    subset = frame.filter(pl.col("split") == "test").drop_nulls(subset=[target])
    if target == "tail_event_20d":
        import numpy as np

        labels = np.array(
            [1.0 if value else 0.0 for value in subset.get_column(target).to_list()],
            dtype=np.float64,
        )
    else:
        labels = subset.get_column(target).to_numpy()
    return subset.select(features).to_numpy(), labels


def _native_params(params: dict[str, Any], task: str, seed: int, nthread: int) -> dict[str, Any]:
    native = {
        "max_depth": int(params["max_depth"]),
        "eta": float(params["eta"]),
        "min_child_weight": float(params["min_child_weight"]),
        "subsample": float(params["subsample"]),
        "colsample_bytree": float(params["colsample_bytree"]),
        "lambda": float(params["reg_lambda"]),
        "alpha": float(params["reg_alpha"]),
        "gamma": float(params["gamma"]),
        "seed": seed,
        "nthread": nthread,
        "objective": "binary:logistic" if task == "classification" else "reg:squarederror",
    }
    return native


def _short(target: str) -> str:
    if "vol" in target:
        return "volatility"
    if "drawdown" in target:
        return "drawdown"
    return "tail"


def _log_mlflow(
    root: Path,
    spec: StudySpec,
    metadata: dict[str, Any],
    model_path: Path,
) -> str | None:
    try:
        import os

        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        import mlflow
    except Exception:
        return None
    db = root / "data" / "mlflow" / "mlflow.db"
    artifacts = root / "artifacts" / "mlflow"
    db.parent.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{db.resolve().as_posix()}")
    experiment = mlflow.get_experiment_by_name(spec.experiment_id)
    if experiment is None:
        mlflow.create_experiment(spec.experiment_id, artifact_location=artifacts.resolve().as_uri())
    mlflow.set_experiment(spec.experiment_id)
    try:
        with mlflow.start_run(run_name=f"{spec.study_name}-{metadata['model_version']}") as run:
            mlflow.set_tags(
                {
                    "target": spec.target,
                    "feature_family": spec.feature_family,
                    "dataset_fingerprint": str(metadata["dataset_fingerprint"]),
                    "state": "CANDIDATE",
                }
            )
            flat = {
                key: value
                for key, value in metadata.get("parameters", {}).items()
                if isinstance(value, (int, float, str))
            }
            if flat:
                mlflow.log_params(flat)
            for split, values in metadata.get("metrics", {}).items():
                if isinstance(values, dict):
                    mlflow.log_metrics(
                        {f"{split}_{name}": float(metric) for name, metric in values.items()}
                    )
            mlflow.log_artifact(str(model_path))
            return str(run.info.run_id)
    except Exception:
        return None


def config_from_path(path: Path | None = None) -> ExperimentFile:
    return load_experiment_file(path or default_config_path())
