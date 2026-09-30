"""Phase 1 path from a holdings payload to stored genome and drift results."""

from __future__ import annotations

import logging
from typing import Any

import polars as pl
from pydantic import BaseModel

from etf_genome.config.settings import AppSettings
from etf_genome.data.storage.errors import StorageError
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.domain.models import DriftReport, GenomeSnapshotReport
from etf_genome.drift import compute_drift
from etf_genome.errors import EtfGenomeError
from etf_genome.features.errors import CalculationError
from etf_genome.genome import build_genome_report
from etf_genome.services.sample_data import (
    load_sample_payload,
    metadata_from_frame,
    normalize_payload,
)

logger = logging.getLogger(__name__)


class VerticalSliceResult(BaseModel):
    """Serializable output of the Phase 1 holdings path."""

    fund_id: str
    warnings: list[str]
    earlier: GenomeSnapshotReport
    later: GenomeSnapshotReport
    drift: DriftReport
    parquet_paths: list[str]
    stored_holding_rows: int
    analytics_engine: str


def run_vertical_slice(
    settings: AppSettings,
    payload: dict[str, Any] | None = None,
) -> VerticalSliceResult:
    """Normalize, store, and compare the earliest and latest snapshots.

    Feature calculations read the Parquet files back, so a successful result
    has been through local storage rather than only through in-memory frames.
    """

    settings.ensure_directories()
    loaded = payload if payload is not None else load_sample_payload()
    normalized = normalize_payload(loaded)
    metadata = metadata_from_frame(normalized.frame)
    store = LocalHoldingsStore(settings)
    paths = store.write_holdings(normalized.frame, metadata)

    dates = sorted(normalized.frame.get_column("snapshot_date").unique().to_list())
    if len(dates) < 2:
        raise CalculationError("Mandate drift needs at least two snapshot dates")
    earlier = store.read_holdings(metadata.fund_id, dates[0])
    later = store.read_holdings(metadata.fund_id, dates[-1])
    summary, analytics_engine = store.summarize()
    expected_rows = earlier.height + later.height
    stored_rows = int(summary.select(pl.col("holding_count").sum()).item() or 0)
    if stored_rows < expected_rows:
        raise StorageError(
            "DuckDB summary does not see every holding written to Parquet "
            f"(saw {stored_rows}, expected at least {expected_rows})"
        )

    result = VerticalSliceResult(
        fund_id=metadata.fund_id,
        warnings=normalized.warnings,
        earlier=build_genome_report(earlier),
        later=build_genome_report(later),
        drift=compute_drift(earlier, later),
        parquet_paths=paths,
        stored_holding_rows=stored_rows,
        analytics_engine=analytics_engine,
    )
    logger.info(
        "Completed Phase 1 vertical slice",
        extra={"fund_id": metadata.fund_id, "snapshot_date": str(dates[-1])},
    )
    return result


def main() -> int:
    """Print the Phase 1 drift report as JSON."""

    import json
    import sys

    from etf_genome.logging_config import configure_logging

    settings = AppSettings()
    configure_logging(settings)
    try:
        result = run_vertical_slice(settings)
    except EtfGenomeError as exc:
        logger.error("%s", exc)
        print(f"ETF Genome error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0
