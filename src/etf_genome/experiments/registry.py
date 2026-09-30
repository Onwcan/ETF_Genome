"""Local model lifecycle. The desktop reads this file and does not import MLflow."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATES = {"EXPERIMENT", "CANDIDATE", "PRODUCTION", "ARCHIVED"}


class PromotionError(RuntimeError):
    """Raised when a model is not allowed to become production."""


@dataclass
class ModelRecord:
    model_id: str
    model_version: str
    state: str
    target: str
    feature_family: str
    dataset_fingerprint: str
    dataset_version: str
    feature_version: str
    target_version: str
    artifact: str
    train_end: str
    validation_end: str
    created_at: str
    optuna_study: str | None = None
    wandb_run: str | None = None
    mlflow_run: str | None = None
    metrics: dict[str, Any] | None = None
    fund_id: str = "cik:0001067839|series:S000101292"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class ModelRegistryService:
    """Explicit promotion. A newer candidate does not replace production."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "models" / "registry" / "registry.json"

    def list_models(self) -> list[ModelRecord]:
        return [_record(item) for item in self._read()]

    def register_candidate(
        self,
        record: ModelRecord,
        source_model: Path,
        source_meta: Path,
    ) -> ModelRecord:
        if record.state != "CANDIDATE":
            raise PromotionError("New records enter as CANDIDATE.")
        self._require_files(source_model, source_meta)
        destination = self.root / "models" / "candidates" / record.model_id / record.model_version
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_model, destination / "model.json")
        shutil.copy2(source_meta, destination / "model.metadata.json")
        relative = Path("models") / "candidates" / record.model_id / record.model_version
        record.artifact = str(relative / "model.json")
        rows = [item for item in self._read() if not _same(item, record)]
        rows.append(record.to_json())
        self._write(rows)
        return record

    def promote(self, model_id: str, model_version: str) -> ModelRecord:
        rows = self._read()
        chosen = next(
            (
                item
                for item in rows
                if item["model_id"] == model_id and item["model_version"] == model_version
            ),
            None,
        )
        if chosen is None:
            raise PromotionError(f"{model_id} version {model_version} is not registered.")
        record = _record(chosen)
        artifact = self.root / record.artifact
        meta = artifact.with_name("model.metadata.json")
        self._require_files(artifact, meta)
        metadata = json.loads(meta.read_text(encoding="utf-8"))
        if not record.dataset_fingerprint:
            raise PromotionError("Dataset fingerprint is missing.")
        if metadata.get("target") != record.target:
            raise PromotionError("Model metadata target does not match the registry record.")
        features = metadata.get("features")
        if not isinstance(features, list) or not features:
            raise PromotionError("Feature schema is missing.")
        metrics = record.metrics or {}
        if "test" not in metrics:
            raise PromotionError("Untouched test metrics are required before promotion.")
        self._smoke(artifact, metadata)
        for item in rows:
            if (
                item["state"] == "PRODUCTION"
                and item["target"] == record.target
                and item["feature_family"] == record.feature_family
            ):
                item["state"] = "ARCHIVED"
        production = self.root / "models" / "production" / record.model_id / record.model_version
        production.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifact, production / "model.json")
        shutil.copy2(meta, production / "model.metadata.json")
        record.state = "PRODUCTION"
        record.artifact = str(
            Path("models") / "production" / record.model_id / record.model_version / "model.json"
        )
        updated = [record.to_json() if _same(item, record) else item for item in rows]
        self._write(updated)
        return record

    def get_production_model(
        self,
        fund_id: str,
        target: str,
        feature_family: str,
    ) -> ModelRecord | None:
        matches = [
            record
            for record in self.list_models()
            if record.state == "PRODUCTION"
            and record.fund_id == fund_id
            and record.target == target
            and record.feature_family == feature_family
        ]
        return matches[-1] if matches else None

    def _smoke(self, artifact: Path, metadata: dict[str, Any]) -> None:
        import xgboost as xgb

        booster = xgb.Booster()
        booster.load_model(str(artifact))
        features = metadata["features"]
        if not isinstance(features, list) or not features:
            raise PromotionError("Feature schema is empty.")

    def _require_files(self, model: Path, meta: Path) -> None:
        if not model.is_file() or not meta.is_file():
            raise PromotionError("Model artifact or metadata is missing.")

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        rows = payload.get("models", [])
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"models": rows}, indent=2), encoding="utf-8")


def new_record(**kwargs: Any) -> ModelRecord:
    kwargs.setdefault("created_at", datetime.now(UTC).isoformat())
    kwargs.setdefault("state", "CANDIDATE")
    return ModelRecord(**kwargs)


def _record(item: dict[str, Any]) -> ModelRecord:
    return ModelRecord(**item)


def _same(item: dict[str, Any], record: ModelRecord) -> bool:
    same_id = item.get("model_id") == record.model_id
    same_version = item.get("model_version") == record.model_version
    return same_id and same_version
