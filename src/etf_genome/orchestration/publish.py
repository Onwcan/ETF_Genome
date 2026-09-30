"""Atomic publication of a validated risk dataset."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.features.risk.dataset import (
    DATASET_VERSION,
    FEATURE_VERSION,
    TARGET_VERSION,
    build_holdings_timeline,
    build_risk_dataset,
)

LIVE_FILES = (
    "qqq_risk_dataset.parquet",
    "qqq_holdings_timeline.parquet",
    "qqq_risk_dataset_meta.json",
    "dataset_ready.json",
)


class DatasetNotReady(RuntimeError):
    """Raised when a dataset must not replace the last good artifact."""


def validate_point_in_time(frame: pl.DataFrame) -> None:
    """Reject holdings that appear before their SEC filing date."""

    required = {"trading_date", "available_from", "holding_count", "split"}
    missing = required.difference(frame.columns)
    if missing:
        raise DatasetNotReady(f"Dataset is missing columns: {sorted(missing)}")
    leaked = frame.filter(
        pl.col("holding_count").is_not_null()
        & pl.col("available_from").is_not_null()
        & (pl.col("available_from") > pl.col("trading_date"))
    )
    if leaked.height:
        raise DatasetNotReady("Holdings are attached before their publication date.")


def build_manifest(
    frame: pl.DataFrame,
    meta: dict[str, object],
    timeline: pl.DataFrame,
) -> dict[str, object]:
    fingerprint = meta.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise DatasetNotReady("Dataset fingerprint is missing.")
    dates = frame.get_column("trading_date").drop_nulls().to_list() if frame.height else []
    holdings_through = None
    if timeline.height and "publication_date" in timeline.columns:
        published = timeline.get_column("publication_date").drop_nulls().to_list()
        if published:
            holdings_through = str(max(published))
    provider = meta.get("provider")
    market_provider = "twelvedata"
    if isinstance(provider, list) and provider and isinstance(provider[0], str):
        market_provider = provider[0]
    return {
        "dataset_version": str(meta.get("dataset_version") or DATASET_VERSION),
        "feature_version": str(meta.get("feature_version") or FEATURE_VERSION),
        "target_version": str(meta.get("target_version") or TARGET_VERSION),
        "fingerprint": fingerprint,
        "created_at": datetime.now(UTC).isoformat(),
        "market_provider": market_provider,
        "market_through": None if not dates else str(max(dates)),
        "holdings_through": holdings_through,
        "row_count": frame.height,
        "validation_status": "PASSED",
    }


def publish_prepared(
    directory: Path,
    frame: pl.DataFrame,
    timeline: pl.DataFrame,
    meta: dict[str, object],
) -> dict[str, object]:
    """Validate, stage, then replace the live files.

    A validation failure leaves the previous dataset in place.
    """

    validate_point_in_time(frame)
    manifest = build_manifest(frame, meta, timeline)
    directory.mkdir(parents=True, exist_ok=True)
    staging = directory / ".dataset-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        frame.write_parquet(staging / "qqq_risk_dataset.parquet")
        timeline.write_parquet(staging / "qqq_holdings_timeline.parquet")
        staged_meta = dict(meta)
        staged_meta["created_at"] = manifest["created_at"]
        (staging / "qqq_risk_dataset_meta.json").write_text(
            json.dumps(staged_meta, indent=2, default=str),
            encoding="utf-8",
        )
        (staging / "dataset_ready.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        for name in LIVE_FILES:
            (staging / name).replace(directory / name)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    return manifest


def publish_risk_dataset(settings: AppSettings) -> dict[str, object]:
    """Build the current point-in-time table and publish it if validation passes."""

    frame, meta = build_risk_dataset(settings)
    timeline = build_holdings_timeline(settings)
    directory = settings.processed_dir / "features"
    return publish_prepared(directory, frame, timeline, meta)


def load_manifest(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DatasetNotReady("Dataset manifest is not an object.")
    return payload


def require_fingerprint(manifest: dict[str, object], expected: str) -> None:
    """Stop ML orchestration when the artifact is not the expected dataset."""

    if manifest.get("validation_status") != "PASSED":
        raise DatasetNotReady("Dataset manifest is not marked PASSED.")
    actual = manifest.get("fingerprint")
    if actual != expected:
        raise DatasetNotReady(f"Dataset fingerprint {actual} does not match {expected}.")
