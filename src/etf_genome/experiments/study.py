"""Persistent Optuna studies. The final test split never enters the objective."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import optuna
import polars as pl

from etf_genome.experiments.booster import (
    SplitLeakError,
    average_precision,
    fit_booster,
    matrices,
    predict,
    regression_scores,
    suggest_params,
    tuning_frame,
)
from etf_genome.experiments.config import StudySpec

optuna.logging.set_verbosity(optuna.logging.WARNING)


class DatasetFingerprintError(RuntimeError):
    """Raised when a saved study belongs to a different dataset."""


def study_storage(root: Path) -> str:
    path = root / "data" / "optuna" / "optuna.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.resolve().as_posix()}"


def study_name(base: str, fingerprint: str) -> str:
    return f"{base}-{fingerprint[:12]}"


def open_study(
    *,
    storage: str,
    base_name: str,
    fingerprint: str,
    direction: Literal["minimize", "maximize"],
    resume: bool,
    seed: int = 42,
) -> optuna.Study:
    name = study_name(base_name, fingerprint)
    study = optuna.create_study(
        study_name=name,
        storage=storage,
        direction=direction,
        load_if_exists=resume,
        sampler=optuna.samplers.TPESampler(seed=seed),
    )
    existing = study.user_attrs.get("dataset_fingerprint")
    if existing and existing != fingerprint:
        raise DatasetFingerprintError(
            f"Study {name} is bound to dataset {existing}, not {fingerprint}."
        )
    if not existing:
        study.set_user_attr("dataset_fingerprint", fingerprint)
    return study


def run_study(
    study: optuna.Study,
    frame: pl.DataFrame,
    spec: StudySpec,
    *,
    n_trials: int,
    seed: int,
    nthread: int,
    round_min: int,
    round_max: int,
) -> optuna.Study:
    scoped = frame
    if spec.feature_family == "genome":
        scoped = frame.filter(pl.col("holding_count").is_not_null())
    safe = tuning_frame(scoped)
    if "test" in set(safe.get_column("split").drop_nulls().to_list()):
        raise SplitLeakError("Objective frame still contains test rows.")
    features = spec.features()
    completed = sum(trial.state == optuna.trial.TrialState.COMPLETE for trial in study.trials)
    remaining = max(0, n_trials - completed)
    if remaining == 0:
        return study

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, task=spec.task, seed=seed, nthread=nthread)
        rounds = trial.suggest_int("num_boost_round", round_min, round_max)
        x_train, y_train = matrices(safe, features, spec.target, "train")
        x_valid, y_valid = matrices(safe, features, spec.target, "validation")
        if len(y_train) == 0 or len(y_valid) == 0:
            raise RuntimeError("Training or validation split is empty.")
        booster = fit_booster(x_train, y_train, x_valid, y_valid, features, params, rounds)
        scores = predict(booster, x_valid, features)
        if spec.task == "classification":
            value = average_precision(y_valid, scores)
            trial.set_user_attr("validation_pr_auc", value)
            return value
        metrics = regression_scores(y_valid, scores)
        trial.set_user_attr("validation_mae", metrics["mae"])
        trial.set_user_attr("validation_rmse", metrics["rmse"])
        trial.set_user_attr("validation_r2", metrics["r2"])
        return metrics["mae"]

    study.optimize(objective, n_trials=remaining, catch=(Exception,), show_progress_bar=False)
    return study


def best_complete_trial(study: optuna.Study) -> optuna.trial.FrozenTrial:
    complete = [trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE]
    if not complete:
        raise RuntimeError(f"Study {study.study_name} has no completed trial.")
    if study.direction == optuna.study.StudyDirection.MAXIMIZE:
        return max(complete, key=lambda trial: float(trial.value or float("-inf")))

    def _loss(trial: optuna.trial.FrozenTrial) -> float:
        if trial.value is None:
            return float("inf")
        return float(trial.value)

    return min(complete, key=_loss)


def trial_counts(study: optuna.Study) -> dict[str, int]:
    counts = {"complete": 0, "failed": 0, "pruned": 0, "other": 0}
    for trial in study.trials:
        if trial.state == optuna.trial.TrialState.COMPLETE:
            counts["complete"] += 1
        elif trial.state == optuna.trial.TrialState.FAIL:
            counts["failed"] += 1
        elif trial.state == optuna.trial.TrialState.PRUNED:
            counts["pruned"] += 1
        else:
            counts["other"] += 1
    return counts


def refit_best(
    frame: pl.DataFrame,
    spec: StudySpec,
    params: dict[str, Any],
    num_boost_round: int,
) -> Any:
    """Refit the frozen parameters. Callers may score test only after this returns."""

    safe = tuning_frame(
        frame.filter(pl.col("holding_count").is_not_null())
        if spec.feature_family == "genome"
        else frame
    )
    features = spec.features()
    x_train, y_train = matrices(safe, features, spec.target, "train")
    x_valid, y_valid = matrices(safe, features, spec.target, "validation")
    return fit_booster(x_train, y_train, x_valid, y_valid, features, params, num_boost_round)
