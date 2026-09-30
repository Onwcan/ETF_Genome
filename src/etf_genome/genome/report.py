"""Phase 1 genome report for one canonical snapshot."""

from __future__ import annotations

import polars as pl

from etf_genome.domain.models import GenomeSnapshotReport
from etf_genome.features.concentration.metrics import (
    compute_concentration,
    country_allocation,
    largest_positions,
    sector_allocation,
)
from etf_genome.features.snapshot import require_single_snapshot


def build_genome_report(frame: pl.DataFrame, *, position_limit: int = 10) -> GenomeSnapshotReport:
    """Build the genome view the desktop shell and the vertical slice share."""

    snapshot = require_single_snapshot(frame)
    row = snapshot.row(0, named=True)
    return GenomeSnapshotReport(
        fund_id=str(row["fund_id"]),
        fund_name=row.get("fund_name"),
        ticker=row.get("ticker"),
        snapshot_date=row["snapshot_date"],
        concentration=compute_concentration(snapshot),
        sector_exposure=sector_allocation(snapshot),
        country_exposure=country_allocation(snapshot),
        largest_positions=largest_positions(snapshot, limit=position_limit),
    )
