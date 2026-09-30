"""Train the QQQ 20-day risk baselines. This module does not touch the UI."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
import polars as pl

from etf_genome.config.paths import project_root
from etf_genome.config.settings import AppSettings
from etf_genome.features.market.series import GENOME_FEATURES, MARKET_FEATURES
from etf_genome.features.risk.dataset import (
    DATASET_VERSION,
    FEATURE_VERSION,
    TARGET_VERSION,
    TRAIN_END,
    VALIDATION_END,
    write_dataset,
)

SEED = 42
TARGETS = ("forward_realized_vol_20d", "forward_max_drawdown_20d")
XGB_PARAMS: dict[str, int | float | str] = {
    "n_estimators": 200,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "random_state": SEED,
    "n_jobs": 1,
    "objective": "reg:squarederror",
}
MIN_TRAIN = 50
MIN_EVAL = 20


def train_risk_baseline(
    settings: AppSettings,
    *,
    output_root: Path | None = None,
) -> dict[str, object]:
    """Build the dataset, fit baselines, and write artifacts under ``models/``."""

    meta = write_dataset(settings)
    frame = pl.read_parquet(settings.processed_dir / "features" / "qqq_risk_dataset.parquet")
    summary = _audit(frame)
    if (
        summary["train"] < MIN_TRAIN
        or summary["validation"] < MIN_EVAL
        or summary["test"] < MIN_EVAL
    ):
        raise RuntimeError(
            "Not enough purged out-of-time rows to train a risk baseline: " + json.dumps(summary)
        )
    root = output_root or project_root()
    directory = root / "models" / "risk_baseline"
    directory.mkdir(parents=True, exist_ok=True)
    reports = root / "reports" / "risk_baseline"
    reports.mkdir(parents=True, exist_ok=True)
    comparisons: dict[str, list[dict[str, object]]] = {}
    importances: dict[str, list[_GainRow]] = {}
    artifacts: list[str] = []
    import xgboost

    for target in TARGETS:
        comparisons[target] = []
        naive_column = "realized_vol_20d" if "vol" in target else "rolling_max_drawdown_20d"
        comparisons[target].append(_naive(frame, target, naive_column))
        comparisons[target].extend(_sklearn_baselines(frame, target))
        market_name = f"qqq_market_{_short(target)}_xgb"
        genome_name = f"qqq_genome_{_short(target)}_xgb"
        market_metrics, market_importance = _xgboost(
            frame, target, MARKET_FEATURES, market_name, directory, meta
        )
        genome_frame = frame.filter(pl.col("holding_count").is_not_null())
        genome_ok = all(
            genome_frame.filter(pl.col("split") == split).height
            >= (MIN_TRAIN if split == "train" else MIN_EVAL)
            for split in ("train", "validation", "test")
        )
        if genome_ok:
            genome_metrics, genome_importance = _xgboost(
                genome_frame,
                target,
                [*MARKET_FEATURES, *GENOME_FEATURES],
                genome_name,
                directory,
                meta,
            )
            importances[genome_name] = genome_importance
            artifacts.append(genome_name)
        else:
            genome_metrics = {
                "model": genome_name,
                "target": target,
                "status": "insufficient genome-aware rows",
                "metrics": {},
            }
        comparisons[target].extend([market_metrics, genome_metrics])
        importances[market_name] = market_importance
        artifacts.append(market_name)
    tail = _tail_counts(frame)
    tail_models: list[dict[str, object]] = []
    if tail["classifier"] == "sufficient tail events":
        tail_models.extend(
            _train_tail_model(frame, MARKET_FEATURES, "qqq_market_tail_20d_xgb", directory, meta)
        )
        genome_frame = frame.filter(pl.col("holding_count").is_not_null())
        genome_tail = _tail_counts(genome_frame)
        if genome_tail["classifier"] == "sufficient tail events":
            tail_models.extend(
                _train_tail_model(
                    genome_frame,
                    [*MARKET_FEATURES, *GENOME_FEATURES],
                    "qqq_genome_tail_20d_xgb",
                    directory,
                    meta,
                )
            )
            tail["classifier"] = "trained"
        else:
            tail["genome_classifier"] = "insufficient tail events"
            tail["classifier"] = "trained" if tail_models else "insufficient tail events"
        for item in tail_models:
            if item.get("status") == "trained":
                artifacts.append(str(item["model"]))
    report = {
        "dataset": meta,
        "audit": summary,
        "tail_events": tail,
        "tail_models": tail_models,
        "comparisons": comparisons,
        "feature_importance": importances,
        "artifacts": artifacts,
        "xgboost_version": xgboost.__version__,
        "sklearn_version": _sklearn_version(),
        "seed": SEED,
        "parameters": XGB_PARAMS,
        "missingness": _missingness(frame),
        "target_statistics": _target_statistics(frame),
        "trained_at": datetime.now(UTC).isoformat(),
        "train_end": TRAIN_END.isoformat(),
        "validation_end": VALIDATION_END.isoformat(),
        "limitations": [
            "Out-of-time risk estimates for one ETF. Not a trading signal.",
            "A positive R^2 is not evidence of market predictability, alpha, or causality.",
            "Sector features are unavailable because N-PORT did not supply them.",
            "Twelve Data adjust=all is one OHLC series. adjusted_* fields stay null.",
        ],
    }
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "dataset_version": DATASET_VERSION,
                "feature_version": FEATURE_VERSION,
                "target_version": TARGET_VERSION,
                "fingerprint": meta.get("fingerprint"),
                "seed": SEED,
                "xgboost_version": xgboost.__version__,
                "sklearn_version": _sklearn_version(),
                "parameters": XGB_PARAMS,
                "train_end": TRAIN_END.isoformat(),
                "validation_end": VALIDATION_END.isoformat(),
                "trained_at": report["trained_at"],
                "artifacts": artifacts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (reports / "metrics.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    (reports / "report.md").write_text(_markdown(report), encoding="utf-8")
    (directory / "feature_schema.json").write_text(
        json.dumps(
            {
                "market_features": MARKET_FEATURES,
                "genome_features": GENOME_FEATURES,
                "feature_version": FEATURE_VERSION,
                "target_version": TARGET_VERSION,
                "dataset_version": DATASET_VERSION,
                "fingerprint": meta.get("fingerprint"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return report


def _audit(frame: pl.DataFrame) -> dict[str, int]:
    counts = {str(key): int(value) for key, value in frame.group_by("split").len().iter_rows()}
    return {
        "total": frame.height,
        "with_market_features": int(frame.filter(pl.col("return_1d").is_not_null()).height),
        "with_genome_features": int(frame.filter(pl.col("holding_count").is_not_null()).height),
        "warmup": counts.get("warmup", 0),
        "no_target": counts.get("no_target", 0),
        "missing_target": int(frame.filter(pl.col("forward_realized_vol_20d").is_null()).height),
        "train": counts.get("train", 0),
        "validation": counts.get("validation", 0),
        "test": counts.get("test", 0),
        "purged_train": counts.get("purged_train", 0),
        "purged_validation": counts.get("purged_validation", 0),
    }


def _xy(
    frame: pl.DataFrame, features: list[str], target: str, split: str
) -> tuple[np.ndarray, np.ndarray]:
    subset = (
        frame.filter(pl.col("split") == split)
        .select([*features, target])
        .drop_nulls(subset=[target])
    )
    return subset.select(features).to_numpy(), subset.get_column(target).to_numpy()


def _scores(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    error = np.asarray(y_pred, dtype=np.float64) - np.asarray(y_true, dtype=np.float64)
    mae = float(np.mean(np.abs(error)))
    rmse = float(np.sqrt(np.mean(error**2)))
    center = np.asarray(y_true, dtype=np.float64) - float(np.mean(y_true))
    total = float(np.sum(center**2))
    r2 = float("nan") if total == 0 else float(1.0 - np.sum(error**2) / total)
    return {"mae": mae, "rmse": rmse, "r2": r2}


def _sklearn_version() -> str:
    try:
        import sklearn
    except ImportError:
        return "unavailable"
    return str(sklearn.__version__)


def _sklearn_baselines(frame: pl.DataFrame, target: str) -> list[dict[str, object]]:
    """Fit the small scikit-learn comparison set on training rows only."""

    try:
        from sklearn.dummy import DummyRegressor
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import Pipeline
    except ImportError as exc:
        blocked = "Windows Application Control blocked the scikit-learn native library"
        return [
            {
                "model": name,
                "target": target,
                "status": blocked,
                "metrics": {},
                "detail": type(exc).__name__,
            }
            for name in ("ridge_market", "dummy_market", "hist_gradient_boosting_market")
        ]
    ridge = Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", Ridge(alpha=1.0))])
    dummy = DummyRegressor(strategy="mean")
    boosting = HistGradientBoostingRegressor(
        max_depth=3,
        max_iter=100,
        learning_rate=0.05,
        random_state=SEED,
    )
    return [
        _fit_estimator(frame, target, "ridge_market", ridge),
        _fit_estimator(frame, target, "dummy_market", dummy),
        _fit_estimator(frame, target, "hist_gradient_boosting_market", boosting),
    ]


def _fit_estimator(
    frame: pl.DataFrame,
    target: str,
    name: str,
    model: object,
) -> dict[str, object]:
    x_train, y_train = _xy(frame, MARKET_FEATURES, target, "train")
    model.fit(x_train, y_train)  # type: ignore[attr-defined]  # sklearn estimator, no py.typed
    metrics = {}
    for split in ("validation", "test"):
        x_split, y_split = _xy(frame, MARKET_FEATURES, target, split)
        predicted = np.asarray(model.predict(x_split))  # type: ignore[attr-defined]  # sklearn estimator
        metrics[split] = _scores(y_split, predicted)
    return {"model": name, "target": target, "metrics": metrics}


def _naive(frame: pl.DataFrame, target: str, column: str) -> dict[str, object]:
    metrics = {}
    for split in ("validation", "test"):
        subset = frame.filter(pl.col("split") == split).select([column, target]).drop_nulls()
        metrics[split] = _scores(
            subset.get_column(target).to_numpy(), subset.get_column(column).to_numpy()
        )
    return {"model": f"naive_{column}", "target": target, "metrics": metrics}


class _GainRow(TypedDict):
    feature: str
    gain: float


def _native_params() -> dict[str, float | int | str]:
    return {
        "max_depth": int(XGB_PARAMS["max_depth"]),
        "eta": float(XGB_PARAMS["learning_rate"]),
        "subsample": float(XGB_PARAMS["subsample"]),
        "colsample_bytree": float(XGB_PARAMS["colsample_bytree"]),
        "objective": str(XGB_PARAMS["objective"]),
        "seed": int(XGB_PARAMS["random_state"]),
        "nthread": 1,
    }


def _fit_xgboost(
    xgb: Any,
    x_train: np.ndarray,
    y_train: np.ndarray,
    features: list[str],
    path: Path,
) -> tuple[str, Callable[[np.ndarray], np.ndarray], Any, str]:
    """Fit XGBoost. Use the native booster when the sklearn wrapper cannot load."""

    try:
        model = xgb.XGBRegressor(**XGB_PARAMS)
        model.fit(x_train, y_train)
        model.save_model(path)
        fitted = model.get_booster()

        def predict_wrapper(values: np.ndarray) -> np.ndarray:
            return np.asarray(model.predict(values))

        return "XGBRegressor", predict_wrapper, fitted, str(xgb.__version__)
    except ImportError:
        matrix = xgb.DMatrix(
            x_train,
            label=y_train,
            feature_names=features,
            missing=np.nan,
        )
        booster = xgb.train(
            _native_params(),
            matrix,
            num_boost_round=int(XGB_PARAMS["n_estimators"]),
        )
        booster.save_model(path)

        def predict_booster(values: np.ndarray) -> np.ndarray:
            matrix = xgb.DMatrix(values, feature_names=features, missing=np.nan)
            return np.asarray(booster.predict(matrix))

        return "xgboost.Booster", predict_booster, booster, str(xgb.__version__)


def _xgboost(
    frame: pl.DataFrame,
    target: str,
    features: list[str],
    name: str,
    directory: Path,
    meta: dict[str, object],
) -> tuple[dict[str, object], list[_GainRow]]:
    import xgboost as xgb

    x_train, y_train = _xy(frame, features, target, "train")
    path = directory / f"{name}.json"
    model_type, predict, booster, xgb_version = _fit_xgboost(xgb, x_train, y_train, features, path)
    metrics = {}
    for split in ("validation", "test"):
        x_split, y_split = _xy(frame, features, target, split)
        metrics[split] = _scores(y_split, np.asarray(predict(x_split)))
    (directory / f"{name}.metadata.json").write_text(
        json.dumps(
            {
                "model_id": name,
                "model_type": model_type,
                "target": target,
                "features": features,
                "seed": SEED,
                "train_end": TRAIN_END.isoformat(),
                "validation_end": VALIDATION_END.isoformat(),
                "dataset_version": DATASET_VERSION,
                "feature_version": FEATURE_VERSION,
                "target_version": TARGET_VERSION,
                "metrics": metrics,
                "parameters": XGB_PARAMS,
                "xgboost_version": xgb_version,
                "sklearn_version": _sklearn_version(),
                "fingerprint": meta.get("fingerprint"),
                "trained_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    gain = booster.get_score(importance_type="gain")
    ranked_rows: list[_GainRow] = []
    for key, value in gain.items():
        if key.startswith("f") and key[1:].isdigit():
            feature_name = features[int(key[1:])]
        elif key in features:
            feature_name = key
        else:
            continue
        ranked_rows.append({"feature": feature_name, "gain": _required_float(value)})
    ranked = sorted(ranked_rows, key=lambda item: item["gain"], reverse=True)
    return {"model": name, "target": target, "metrics": metrics}, ranked


def _train_tail_model(
    frame: pl.DataFrame,
    features: list[str],
    name: str,
    directory: Path,
    meta: dict[str, object],
) -> list[dict[str, object]]:
    """Fit one tail classifier. The 8% drawdown cutoff is not tuned on test data."""

    import xgboost as xgb

    def matrix(split: str) -> tuple[np.ndarray, np.ndarray]:
        subset = frame.filter(pl.col("split") == split).drop_nulls(subset=["tail_event_20d"])
        labels = np.array(
            [1.0 if value else 0.0 for value in subset.get_column("tail_event_20d").to_list()],
            dtype=np.float64,
        )
        return subset.select(features).to_numpy(), labels

    x_train, y_train = matrix("train")
    path = directory / f"{name}.json"
    try:
        model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=SEED,
            n_jobs=1,
            objective="binary:logistic",
        )
        model.fit(x_train, y_train)
        model.save_model(path)

        def predict(values: np.ndarray) -> np.ndarray:
            return np.asarray(model.predict_proba(values)[:, 1])

        model_type = "XGBClassifier"
        version = str(xgb.__version__)
    except ImportError:
        params = _native_params()
        params["objective"] = "binary:logistic"
        booster = xgb.train(
            params,
            xgb.DMatrix(x_train, label=y_train, feature_names=features, missing=np.nan),
            num_boost_round=int(XGB_PARAMS["n_estimators"]),
        )
        booster.save_model(path)

        def predict(values: np.ndarray) -> np.ndarray:
            scored = xgb.DMatrix(values, feature_names=features, missing=np.nan)
            return np.asarray(booster.predict(scored))

        model_type = "xgboost.Booster"
        version = str(xgb.__version__)
    metrics = {}
    for split in ("validation", "test"):
        x_split, y_split = matrix(split)
        metrics[split] = _classification_scores(y_split, predict(x_split))
    (directory / f"{name}.metadata.json").write_text(
        json.dumps(
            {
                "model_id": name,
                "model_type": model_type,
                "target": "tail_event_20d",
                "decision_threshold": 0.5,
                "event_threshold": 0.08,
                "features": features,
                "seed": SEED,
                "train_end": TRAIN_END.isoformat(),
                "validation_end": VALIDATION_END.isoformat(),
                "metrics": metrics,
                "xgboost_version": version,
                "fingerprint": meta.get("fingerprint"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return [{"model": name, "status": "trained", "model_type": model_type, "metrics": metrics}]


def _classification_scores(y_true: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    labels = np.asarray(y_true, dtype=np.float64)
    scores = np.asarray(probabilities, dtype=np.float64)
    predicted = scores >= 0.5
    true_positive = float(np.sum(predicted & (labels == 1)))
    false_positive = float(np.sum(predicted & (labels == 0)))
    false_negative = float(np.sum(~predicted & (labels == 1)))
    precision = (
        0.0
        if true_positive + false_positive == 0
        else true_positive / (true_positive + false_positive)
    )
    recall = (
        0.0
        if true_positive + false_negative == 0
        else true_positive / (true_positive + false_negative)
    )
    return {
        "prevalence": float(np.mean(labels)),
        "pr_auc": _average_precision(labels, scores),
        "roc_auc": _roc_auc(labels, scores),
        "brier": float(np.mean((scores - labels) ** 2)),
        "precision": precision,
        "recall": recall,
    }


def _roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    positive = scores[labels == 1]
    negative = scores[labels == 0]
    if positive.size == 0 or negative.size == 0:
        return float("nan")
    difference = positive[:, None] - negative[None, :]
    wins = float(np.sum(difference > 0) + 0.5 * np.sum(difference == 0))
    return wins / float(difference.size)


def _average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(-scores)
    ranked = labels[order]
    hits = np.cumsum(ranked)
    if hits[-1] == 0:
        return float("nan")
    precision = hits / np.arange(1, len(ranked) + 1)
    recall = hits / hits[-1]
    previous = np.concatenate([[0.0], recall[:-1]])
    return float(np.sum((recall - previous) * precision))


def _tail_counts(frame: pl.DataFrame) -> dict[str, object]:
    counts: dict[str, object] = {}
    usable = True
    for split in ("train", "validation", "test"):
        subset = frame.filter(pl.col("split") == split).drop_nulls(subset=["tail_event_20d"])
        positive = int(subset.filter(pl.col("tail_event_20d")).height)
        counts[split] = {"rows": subset.height, "positive": positive}
        if positive < 15:
            usable = False
    counts["classifier"] = "sufficient tail events" if usable else "insufficient tail events"
    return counts


def _missingness(frame: pl.DataFrame) -> dict[str, float]:
    if frame.height == 0:
        return {}
    columns = [*MARKET_FEATURES, *GENOME_FEATURES]
    return {
        column: float(frame.get_column(column).null_count()) / frame.height
        for column in columns
        if column in frame.columns
    }


def _target_statistics(frame: pl.DataFrame) -> dict[str, dict[str, float | None]]:
    stats: dict[str, dict[str, float | None]] = {}
    for target in (*TARGETS, "tail_event_20d"):
        if target not in frame.columns:
            continue
        column = frame.get_column(target).drop_nulls()
        if target == "tail_event_20d":
            stats[target] = {
                "rows": float(column.len()),
                "positive": float(column.sum()) if column.len() else 0.0,
            }
            continue
        if column.len() == 0:
            stats[target] = {"count": 0.0, "mean": None, "min": None, "max": None}
            continue
        stats[target] = {
            "count": float(column.len()),
            "mean": _metric_float(column.mean()),
            "min": _metric_float(column.min()),
            "max": _metric_float(column.max()),
        }
    return stats


def _metric_float(value: object) -> float | None:
    if value is None:
        return None
    return _required_float(value)


def _required_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError("Expected a numeric metric.")
    return float(value)


def _short(target: str) -> str:
    if "vol" in target:
        return "volatility_20d"
    return "drawdown_20d"


def _markdown(report: dict[str, object]) -> str:
    lines = [
        "# QQQ risk baseline",
        "",
        (
            "These figures estimate future risk. They are not forecasts of price "
            "direction and not financial advice."
        ),
        "",
        "Dataset fingerprint: "
        + (
            str(report["dataset"].get("fingerprint")) if isinstance(report["dataset"], dict) else ""
        ),
        "",
        "## Audit",
        "",
        "```json",
        json.dumps(report["audit"], indent=2),
        "```",
        "",
        "## Comparisons",
        "",
    ]
    comparisons = report["comparisons"]
    if isinstance(comparisons, dict):
        for target, rows in comparisons.items():
            lines.append(f"### {target}")
            lines.append("")
            lines.append("| Model | Validation MAE | Test MAE |")
            lines.append("| --- | --- | --- |")
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    metrics = row["metrics"]
                    if not isinstance(metrics, dict):
                        continue
                    validation = metrics.get("validation")
                    test = metrics.get("test")
                    if not isinstance(validation, dict) or not isinstance(test, dict):
                        lines.append(f"| {row['model']} | n/a | n/a |")
                        continue
                    validation_mae = float(validation["mae"])
                    test_mae = float(test["mae"])
                    lines.append(f"| {row['model']} | {validation_mae:.6f} | {test_mae:.6f} |")
            lines.append("")
    lines.append("Tail classification: " + json.dumps(report["tail_events"]))
    lines.extend(
        [
            "",
            "Limitations: these are out-of-time risk estimates for one ETF.",
            "They are not price-direction forecasts, and they are not evidence of alpha.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    """Train from local QQQ history and print the split and metric summary."""

    from etf_genome.logging_config import configure_logging

    settings = AppSettings()
    configure_logging(settings)
    try:
        report = train_risk_baseline(settings)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Risk baseline training stopped: {exc}")
        return 1
    audit = report["audit"]
    print("dataset summary")
    print(json.dumps(audit, indent=2))
    print("temporal split")
    print(f"train through {report['train_end']}; validation through {report['validation_end']}")
    print("purged rows")
    if isinstance(audit, dict):
        purged_train = audit.get("purged_train")
        purged_validation = audit.get("purged_validation")
        print(f"purged_train={purged_train} purged_validation={purged_validation}")
    print("models trained")
    print(json.dumps(report["artifacts"]))
    print("validation metrics and test metrics")
    comparisons = report["comparisons"]
    if isinstance(comparisons, dict):
        for target, rows in comparisons.items():
            print(target)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict):
                    print(f"  {row.get('model')}: {json.dumps(row.get('metrics'))}")
    print("artifact paths")
    print("models/risk_baseline")
    print("reports/risk_baseline/metrics.json")
    print("reports/risk_baseline/report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
