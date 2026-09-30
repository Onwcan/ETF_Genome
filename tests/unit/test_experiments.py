"""Small Optuna, tracking, and registry tests. They do not tune the QQQ study."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import optuna
import polars as pl

from etf_genome.experiments.booster import SplitLeakError, matrices, suggest_params, tuning_frame
from etf_genome.experiments.config import StudySpec
from etf_genome.experiments.registry import ModelRegistryService, PromotionError, new_record
from etf_genome.experiments.study import (
    DatasetFingerprintError,
    best_complete_trial,
    open_study,
    run_study,
    study_name,
    trial_counts,
)
from etf_genome.experiments.tracking import ResearchTracker
from etf_genome.experiments.workflow import _log_mlflow
from etf_genome.features.market.series import GENOME_FEATURES, MARKET_FEATURES


def test_tuning_frame_removes_the_test_split() -> None:
    frame = _frame()
    safe = tuning_frame(frame)
    assert "test" not in safe.get_column("split").to_list()
    try:
        matrices(safe, ["return_1d"], "forward_realized_vol_20d", "test")
    except SplitLeakError:
        return
    raise AssertionError("test split was readable")


def test_study_resumes_without_new_trials_when_the_budget_is_met(tmp_path: Path) -> None:
    storage = f"sqlite:///{(tmp_path / 'optuna.db').as_posix()}"
    fingerprint = "a" * 64
    study = open_study(
        storage=storage,
        base_name="unit-vol",
        fingerprint=fingerprint,
        direction="minimize",
        resume=True,
    )
    run_study(
        study,
        _frame(),
        _spec(),
        n_trials=1,
        seed=42,
        nthread=1,
        round_min=2,
        round_max=2,
    )
    again = open_study(
        storage=storage,
        base_name="unit-vol",
        fingerprint=fingerprint,
        direction="minimize",
        resume=True,
    )
    run_study(
        again,
        _frame(),
        _spec(),
        n_trials=1,
        seed=42,
        nthread=1,
        round_min=2,
        round_max=2,
    )
    assert trial_counts(again)["complete"] == 1
    assert len(again.trials) == 1
    assert best_complete_trial(again).value is not None


def test_dataset_fingerprint_mismatch_rejects_resume(tmp_path: Path) -> None:
    storage = f"sqlite:///{(tmp_path / 'optuna.db').as_posix()}"
    name = study_name("unit-vol", "c" * 64)
    study = optuna.create_study(study_name=name, storage=storage, load_if_exists=True)
    study.set_user_attr("dataset_fingerprint", "d" * 64)
    try:
        open_study(
            storage=storage,
            base_name="unit-vol",
            fingerprint="c" * 64,
            direction="minimize",
            resume=True,
        )
    except DatasetFingerprintError:
        return
    raise AssertionError("fingerprint mismatch was accepted")


def test_failed_trial_does_not_stop_the_study(tmp_path: Path) -> None:
    storage = f"sqlite:///{(tmp_path / 'optuna.db').as_posix()}"
    study = open_study(
        storage=storage,
        base_name="unit-fail",
        fingerprint="e" * 64,
        direction="minimize",
        resume=True,
    )
    empty = _frame().filter(pl.col("split") == "missing")
    run_study(
        study,
        empty,
        _spec(),
        n_trials=1,
        seed=42,
        nthread=1,
        round_min=2,
        round_max=2,
    )
    assert trial_counts(study)["failed"] == 1


def test_wandb_disabled_and_offline_do_not_require_a_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WANDB_MODE", raising=False)
    disabled = ResearchTracker("none", root=tmp_path, run_name="unit", config={"seed": 42})
    assert disabled.start().wandb_mode == "disabled"
    offline = ResearchTracker(
        "wandb",
        root=tmp_path,
        run_name="unit-offline",
        config={"api_key": "nope"},
    )
    result = offline.start()
    offline.log({"validation_mae": 0.1})
    offline.finish()
    assert result.wandb_mode in {"offline", "unavailable", "failed"}
    assert result.wandb_run_id
    assert "nope" not in json_config(offline)


def test_candidate_does_not_replace_production_until_promotion(tmp_path: Path) -> None:
    registry = ModelRegistryService(tmp_path)
    first = _save_model(tmp_path / "v1", "1")
    second = _save_model(tmp_path / "v2", "2")
    registry.register_candidate(first[0], first[1], first[2])
    registry.promote("qqq_market_volatility_xgb", "1")
    registry.register_candidate(second[0], second[1], second[2])
    current = registry.get_production_model(
        "cik:0001067839|series:S000101292",
        "forward_realized_vol_20d",
        "market",
    )
    assert current is not None
    assert current.model_version == "1"
    registry.promote("qqq_market_volatility_xgb", "2")
    promoted = registry.get_production_model(
        "cik:0001067839|series:S000101292",
        "forward_realized_vol_20d",
        "market",
    )
    assert promoted is not None
    assert promoted.model_version == "2"
    archived = [
        record.model_version for record in registry.list_models() if record.state == "ARCHIVED"
    ]
    assert archived == ["1"]


def test_promotion_rejects_a_missing_artifact(tmp_path: Path) -> None:
    registry = ModelRegistryService(tmp_path)
    record = new_record(
        model_id="missing",
        model_version="1",
        target="forward_realized_vol_20d",
        feature_family="market",
        dataset_fingerprint="f" * 64,
        dataset_version="qqq-risk-1",
        feature_version="market-genome-1",
        target_version="fwd-20d-1",
        artifact="models/missing/model.json",
        train_end="2023-12-31",
        validation_end="2024-12-31",
        metrics={"test": {"mae": 0.1}},
    )
    rows = registry._read()
    rows.append(record.to_json())
    registry._write(rows)
    try:
        registry.promote("missing", "1")
    except PromotionError:
        return
    raise AssertionError("missing artifact was promoted")


def test_same_seed_repeats_the_first_trial(tmp_path: Path) -> None:
    first = _one_trial(tmp_path / "a")
    second = _one_trial(tmp_path / "b")
    assert first.params == second.params
    assert first.value == second.value


def test_search_space_stays_inside_the_declared_bounds() -> None:
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42))
    trial = study.ask()
    params = suggest_params(trial, task="regression", seed=42, nthread=1)
    assert params["max_depth"] in {2, 3, 4}
    assert 0.03 <= params["eta"] <= 0.15
    assert 1.0 <= params["min_child_weight"] <= 8.0
    assert 0.7 <= params["subsample"] <= 1.0
    assert 0.7 <= params["colsample_bytree"] <= 1.0
    assert 0.5 <= params["lambda"] <= 5.0
    assert 1e-3 <= params["alpha"] <= 1.0
    assert 0.0 <= params["gamma"] <= 1.0
    assert params["seed"] == 42
    assert params["nthread"] == 1
    assert params["objective"] == "reg:squarederror"
    study.tell(trial, 1.0)


def test_wandb_init_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    import wandb

    def _fail(*_args, **_kwargs):
        raise RuntimeError("offline store failed")

    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.setattr(wandb, "init", _fail)
    tracker = ResearchTracker("wandb", root=tmp_path, run_name="unit-fail", config={"seed": 42})
    result = tracker.start()
    tracker.log({"validation_mae": 0.2})
    tracker.finish()
    assert result.wandb_mode == "failed"
    assert result.errors


def test_mlflow_logs_a_local_run(tmp_path: Path) -> None:
    import mlflow

    model, meta = _tiny_files(tmp_path / "fit")
    spec = _spec()
    metadata = {
        "model_version": "1",
        "dataset_fingerprint": "a" * 64,
        "parameters": {"max_depth": 2, "eta": 0.1},
        "metrics": {"validation": {"mae": 0.2}, "test": {"mae": 0.3}},
    }
    run_id = _log_mlflow(tmp_path, spec, metadata, model)
    assert run_id
    mlflow.set_tracking_uri(f"sqlite:///{(tmp_path / 'data' / 'mlflow' / 'mlflow.db').as_posix()}")
    run = mlflow.get_run(run_id)
    assert run.data.params["max_depth"] == "2"
    assert run.data.metrics["validation_mae"] == 0.2
    assert run.data.metrics["test_mae"] == 0.3
    names = [item.path for item in mlflow.artifacts.list_artifacts(run_id=run_id)]
    assert "model.json" in names
    meta.unlink()


def test_promotion_rejects_a_missing_feature_schema(tmp_path: Path) -> None:
    registry = ModelRegistryService(tmp_path)
    record, model, meta = _save_model(tmp_path / "schema", "1")
    meta.write_text('{"target": "forward_realized_vol_20d"}', encoding="utf-8")
    registry.register_candidate(record, model, meta)
    try:
        registry.promote("qqq_market_volatility_xgb", "1")
    except PromotionError:
        return
    raise AssertionError("missing feature schema was promoted")


def _one_trial(root: Path):
    storage = f"sqlite:///{(root / 'optuna.db').as_posix()}"
    root.mkdir()
    study = open_study(
        storage=storage,
        base_name="unit-vol",
        fingerprint="b" * 64,
        direction="minimize",
        resume=True,
        seed=42,
    )
    run_study(
        study,
        _frame(),
        _spec(),
        n_trials=1,
        seed=42,
        nthread=1,
        round_min=2,
        round_max=2,
    )
    return best_complete_trial(study)


def _tiny_files(directory: Path):
    import xgboost as xgb

    directory.mkdir(parents=True)
    booster = xgb.train(
        {"max_depth": 1, "eta": 0.1, "objective": "reg:squarederror", "seed": 42, "nthread": 1},
        xgb.DMatrix([[0.1], [0.2]], label=[0.2, 0.2], feature_names=["return_1d"]),
        num_boost_round=2,
    )
    model = directory / "model.json"
    meta = directory / "model.metadata.json"
    booster.save_model(model)
    meta.write_text("{}", encoding="utf-8")
    return model, meta


def _spec() -> StudySpec:
    return StudySpec(
        experiment_id="unit",
        study_name="unit-vol",
        target="forward_realized_vol_20d",
        feature_family="market",
        task="regression",
    )


def _frame() -> pl.DataFrame:
    rows = 30
    data: dict[str, object] = {name: [0.1] * rows for name in [*MARKET_FEATURES, *GENOME_FEATURES]}
    data["split"] = ["train"] * 16 + ["validation"] * 8 + ["test"] * 6
    data["forward_realized_vol_20d"] = [0.2] * rows
    data["holding_count"] = [10] * rows
    return pl.DataFrame(data)


def _save_model(directory: Path, version: str):
    import xgboost as xgb

    directory.mkdir(parents=True)
    booster = xgb.train(
        {"max_depth": 1, "eta": 0.1, "objective": "reg:squarederror", "seed": 42, "nthread": 1},
        xgb.DMatrix([[0.1], [0.2]], label=[0.2, 0.2], feature_names=["return_1d"]),
        num_boost_round=2,
    )
    model = directory / "model.json"
    meta = directory / "model.metadata.json"
    booster.save_model(model)
    meta.write_text(
        '{"features": ["return_1d"], "target": "forward_realized_vol_20d"}',
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
        created_at=datetime.now(UTC).isoformat(),
    )
    return record, model, meta


def json_config(tracker: ResearchTracker) -> str:
    return str(tracker.config)
