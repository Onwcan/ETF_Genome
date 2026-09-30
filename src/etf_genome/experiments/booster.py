"""Native XGBoost fits used by Optuna. The test split is not accepted here."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

_ALLOWED = {"train", "validation", "warmup", "no_target", "purged_train", "purged_validation"}


class SplitLeakError(RuntimeError):
    """Raised when a tuning frame still contains the final test split."""


def tuning_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Drop the untouched test split before any trial can see it."""

    if "split" not in frame.columns:
        raise SplitLeakError("Tuning frame has no split column.")
    labels = {str(value) for value in frame.get_column("split").drop_nulls().unique().to_list()}
    if "test" in labels:
        frame = frame.filter(pl.col("split") != "test")
    remaining = {str(value) for value in frame.get_column("split").drop_nulls().unique().to_list()}
    if "test" in remaining:
        raise SplitLeakError("Test rows remained after the firewall.")
    return frame


def matrices(
    frame: pl.DataFrame,
    features: list[str],
    target: str,
    split: str,
) -> tuple[np.ndarray, np.ndarray]:
    if split == "test":
        raise SplitLeakError("Tuning code requested the test split.")
    subset = frame.filter(pl.col("split") == split).drop_nulls(subset=[target])
    if target == "tail_event_20d":
        labels = np.array(
            [1.0 if value else 0.0 for value in subset.get_column(target).to_list()],
            dtype=np.float64,
        )
    else:
        labels = subset.get_column(target).to_numpy().astype(np.float64)
    return subset.select(features).to_numpy(), labels


def fit_booster(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_valid: np.ndarray,
    y_valid: np.ndarray,
    features: list[str],
    params: dict[str, Any],
    num_boost_round: int,
) -> Any:
    import xgboost as xgb

    dtrain = xgb.DMatrix(x_train, label=y_train, feature_names=features, missing=np.nan)
    dvalid = xgb.DMatrix(x_valid, label=y_valid, feature_names=features, missing=np.nan)
    return xgb.train(
        params,
        dtrain,
        num_boost_round=num_boost_round,
        evals=[(dvalid, "validation")],
        early_stopping_rounds=20,
        verbose_eval=False,
    )


def predict(booster: Any, values: np.ndarray, features: list[str]) -> np.ndarray:
    import xgboost as xgb

    matrix = xgb.DMatrix(values, feature_names=features, missing=np.nan)
    return np.asarray(booster.predict(matrix), dtype=np.float64)


def regression_scores(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    actual = np.asarray(y_true, dtype=np.float64)
    predicted = np.asarray(y_pred, dtype=np.float64)
    if actual.size == 0 or predicted.size == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "r2": float("nan")}
    error = predicted - actual
    center = actual - float(np.mean(actual))
    total = float(np.sum(center**2))
    r2 = float("nan") if total == 0 else float(1.0 - np.sum(error**2) / total)
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(np.square(error)))),
        "r2": r2,
    }


def average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(-scores)
    ranked = labels[order]
    hits = np.cumsum(ranked)
    if hits[-1] == 0:
        return float("nan")
    precision = hits / np.arange(1, len(ranked) + 1)
    recall = hits / hits[-1]
    previous = np.concatenate([[0.0], recall[:-1]])
    return float(np.sum((recall - previous) * precision))


def suggest_params(trial: Any, *, task: str, seed: int, nthread: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "max_depth": trial.suggest_int("max_depth", 2, 4),
        "eta": trial.suggest_float("eta", 0.03, 0.15, log=True),
        "min_child_weight": trial.suggest_float("min_child_weight", 1.0, 8.0),
        "subsample": trial.suggest_float("subsample", 0.7, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.7, 1.0),
        "lambda": trial.suggest_float("reg_lambda", 0.5, 5.0, log=True),
        "alpha": trial.suggest_float("reg_alpha", 1e-3, 1.0, log=True),
        "gamma": trial.suggest_float("gamma", 0.0, 1.0),
        "seed": seed,
        "nthread": nthread,
    }
    if task == "classification":
        params["objective"] = "binary:logistic"
        params["eval_metric"] = "aucpr"
    else:
        params["objective"] = "reg:squarederror"
        params["eval_metric"] = "mae"
    return params
