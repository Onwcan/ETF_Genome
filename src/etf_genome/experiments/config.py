"""Typed experiment configuration. Tuning ranges live in the TOML file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from etf_genome.features.market.series import GENOME_FEATURES, MARKET_FEATURES
from etf_genome.features.risk.dataset import (
    DATASET_VERSION,
    FEATURE_VERSION,
    TARGET_VERSION,
    TRAIN_END,
    VALIDATION_END,
)


@dataclass(frozen=True)
class StudySpec:
    experiment_id: str
    study_name: str
    target: str
    feature_family: str
    task: str

    def features(self) -> list[str]:
        if self.feature_family == "market":
            return list(MARKET_FEATURES)
        if self.feature_family == "genome":
            return [*MARKET_FEATURES, *GENOME_FEATURES]
        raise ValueError(f"Unknown feature family: {self.feature_family}")


@dataclass(frozen=True)
class ExperimentFile:
    seed: int
    n_trials: int
    nthread: int
    tracking: str
    num_boost_round_min: int
    num_boost_round_max: int
    studies: tuple[StudySpec, ...]
    dataset_version: str = DATASET_VERSION
    feature_version: str = FEATURE_VERSION
    target_version: str = TARGET_VERSION
    train_end: date = TRAIN_END
    validation_end: date = VALIDATION_END

    def study(self, name: str) -> StudySpec:
        for item in self.studies:
            if item.study_name == name:
                return item
        raise KeyError(name)


def load_experiment_file(path: Path) -> ExperimentFile:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    studies = tuple(
        StudySpec(
            experiment_id=str(item["experiment_id"]),
            study_name=str(item["study_name"]),
            target=str(item["target"]),
            feature_family=str(item["feature_family"]),
            task=str(item["task"]),
        )
        for item in payload["studies"]
    )
    tracking = str(payload.get("tracking", "none"))
    if tracking not in {"none", "wandb", "mlflow", "all"}:
        raise ValueError("tracking must be none, wandb, mlflow, or all")
    for item in studies:
        if item.task not in {"regression", "classification"}:
            raise ValueError(f"{item.study_name} has an unknown task")
        if item.feature_family not in {"market", "genome"}:
            raise ValueError(f"{item.study_name} has an unknown feature family")
    low = int(payload["num_boost_round_min"])
    high = int(payload["num_boost_round_max"])
    if low < 1 or high < low:
        raise ValueError("num_boost_round range is invalid")
    return ExperimentFile(
        seed=int(payload.get("seed", 42)),
        n_trials=int(payload["n_trials"]),
        nthread=int(payload.get("nthread", 1)),
        tracking=tracking,
        num_boost_round_min=low,
        num_boost_round_max=high,
        studies=studies,
    )
