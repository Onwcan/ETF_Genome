"""Guards shared by concentration and drift calculations."""

from __future__ import annotations

import polars as pl

from etf_genome.features.errors import CalculationError


def require_single_snapshot(frame: pl.DataFrame) -> pl.DataFrame:
    """Return ``frame`` when it contains one fund on one date."""

    if frame.is_empty():
        raise CalculationError("Cannot calculate features for an empty holdings snapshot")
    required = {"fund_id", "snapshot_date", "security_id", "portfolio_weight"}
    missing = required.difference(frame.columns)
    if missing:
        raise CalculationError(f"Holdings snapshot is missing columns: {sorted(missing)}")
    keys = frame.select(["fund_id", "snapshot_date"]).unique()
    if keys.height != 1:
        raise CalculationError("Expected holdings for exactly one fund and one snapshot date")
    return frame
