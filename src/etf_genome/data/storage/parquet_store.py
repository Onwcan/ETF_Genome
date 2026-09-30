"""Parquet storage for canonical holdings snapshots."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import polars as pl

from etf_genome.data.storage.errors import SnapshotNotFound, StorageError

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_fund_dirname(fund_id: str) -> str:
    """Encode a fund id as a single Windows-safe directory name."""

    if fund_id.strip() == "" or fund_id.strip() in {".", ".."}:
        raise StorageError("fund_id cannot be empty or a relative path segment")
    if "/" in fund_id or "\\" in fund_id or ".." in fund_id:
        raise StorageError(f"fund_id contains an unsafe path sequence: {fund_id}")
    encoded = _UNSAFE.sub("_", fund_id.strip())
    if encoded in {"", ".", ".."}:
        raise StorageError(f"fund_id cannot be stored as a directory name: {fund_id}")
    return encoded


class ParquetHoldingsStore:
    """Write one Parquet file per fund and snapshot date."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, fund_id: str, snapshot_date: date) -> Path:
        return self.root / safe_fund_dirname(fund_id) / f"{snapshot_date.isoformat()}.parquet"

    def write(self, frame: pl.DataFrame) -> list[Path]:
        """Overwrite the Parquet file for each snapshot present in ``frame``."""

        if frame.is_empty():
            raise StorageError("Cannot store an empty holdings frame")
        required = {"fund_id", "snapshot_date"}
        missing = required.difference(frame.columns)
        if missing:
            raise StorageError(f"Holdings frame is missing columns: {sorted(missing)}")

        written: list[Path] = []
        keys = frame.select(["fund_id", "snapshot_date"]).unique(maintain_order=True)
        for fund_id, snapshot_date in keys.iter_rows():
            if not isinstance(snapshot_date, date):
                raise StorageError("snapshot_date must be a date before it is stored")
            subset = frame.filter(
                (pl.col("fund_id") == fund_id) & (pl.col("snapshot_date") == snapshot_date)
            )
            path = self.path_for(str(fund_id), snapshot_date)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".parquet.tmp")
            subset.write_parquet(temporary)
            temporary.replace(path)
            written.append(path)
        return written

    def read(self, fund_id: str, snapshot_date: date) -> pl.DataFrame:
        path = self.path_for(fund_id, snapshot_date)
        if not path.is_file():
            raise SnapshotNotFound(
                f"No holdings snapshot for {fund_id} on {snapshot_date.isoformat()}"
            )
        return pl.read_parquet(path)

    def list_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.glob("*/*.parquet"))
