"""Optional research tracking. Training still succeeds when W&B is absent."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from etf_genome.logging_config import redact

_PRIVATE_FIELD = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|private[_-]?key|token|password|secret|"
    r"authorization|user[_-]?agent|contact|email)"
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def _scrub_text(value: str) -> str:
    return _EMAIL.sub("[REDACTED_EMAIL]", redact(value))


def _scrub_config(config: dict[str, Any]) -> dict[str, Any]:
    """Copy experiment metadata while omitting private fields at every level."""

    return {
        key: _scrub_value(value)
        for key, value in config.items()
        if key.lower() != "key" and not _PRIVATE_FIELD.search(key) and not _EMAIL.search(key)
    }


def _scrub_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _scrub_config({str(key): item for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return [_scrub_value(item) for item in value]
    if isinstance(value, str):
        return _scrub_text(value)
    return value


@dataclass
class TrackingResult:
    mode: str
    wandb_mode: str
    wandb_run_id: str | None = None
    mlflow_run_id: str | None = None
    errors: list[str] = field(default_factory=list)


class ResearchTracker:
    """Log small metadata. Raw market history and secrets are not uploaded."""

    def __init__(self, mode: str, *, root: Path, run_name: str, config: dict[str, Any]) -> None:
        self.mode = mode
        self.root = root
        self.run_name = _scrub_text(run_name)
        self.config = _scrub_config(config)
        self.result = TrackingResult(mode=mode, wandb_mode="disabled")
        self._wandb: Any = None
        self._started = False

    def start(self) -> TrackingResult:
        if self.mode in {"wandb", "all"}:
            self._start_wandb()
        self._started = True
        return self.result

    def log(self, metrics: dict[str, float], *, step: int | None = None) -> None:
        if self._wandb is None:
            return
        try:
            self._wandb.log(metrics, step=step)
        except Exception as exc:
            self.result.errors.append(f"wandb log failed: {type(exc).__name__}")

    def finish(self) -> TrackingResult:
        if self._wandb is not None:
            try:
                self._wandb.finish()
            except Exception as exc:
                self.result.errors.append(f"wandb finish failed: {type(exc).__name__}")
        return self.result

    def _start_wandb(self) -> None:
        try:
            import wandb
        except ImportError as exc:
            self.result.errors.append(f"wandb import failed: {type(exc).__name__}")
            self.result.wandb_mode = "unavailable"
            return
        wandb_dir = self.root / "artifacts" / "wandb"
        wandb_dir.mkdir(parents=True, exist_ok=True)
        online = os.environ.get("WANDB_MODE") == "online" and bool(os.environ.get("WANDB_API_KEY"))
        try:
            run = wandb.init(
                project="etf-genome-risk",
                name=self.run_name,
                mode="online" if online else "offline",
                dir=str(wandb_dir),
                config=self.config,
                reinit="finish_previous",
            )
        except Exception as exc:
            self.result.errors.append(f"wandb init failed: {type(exc).__name__}")
            self.result.wandb_mode = "failed"
            return
        self._wandb = wandb
        self.result.wandb_mode = "online" if online else "offline"
        self.result.wandb_run_id = None if run is None else str(run.id)
