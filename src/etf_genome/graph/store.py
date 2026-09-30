"""Persist a graph snapshot without replacing a failed build."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from etf_genome.config.settings import AppSettings


def snapshot_dir(settings: AppSettings, universe_id: str, as_of: str) -> Path:
    return settings.processed_dir / "graph" / universe_id / as_of


def write_snapshot(
    settings: AppSettings,
    *,
    universe_id: str,
    as_of: str,
    nodes: pl.DataFrame,
    edges: pl.DataFrame,
    projection: pl.DataFrame,
    crowded: pl.DataFrame,
    manifest: dict[str, object],
) -> Path:
    directory = snapshot_dir(settings, universe_id, as_of)
    staging = directory.parent / f".{as_of}.staging"
    if staging.exists():
        import shutil

        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    nodes.write_parquet(staging / "nodes.parquet")
    edges.write_parquet(staging / "edges.parquet")
    projection.write_parquet(staging / "etf_projection.parquet")
    crowded.write_parquet(staging / "security_crowding.parquet")
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if directory.exists():
        import shutil

        shutil.rmtree(directory)
    staging.rename(directory)
    return directory
