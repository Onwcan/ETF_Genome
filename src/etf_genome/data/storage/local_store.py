"""Facade over Parquet holdings, the SQLite catalog, and DuckDB queries."""

from __future__ import annotations

from datetime import date

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.storage.duckdb_store import DuckDbAnalytics, duckdb_import_error
from etf_genome.data.storage.errors import StorageError
from etf_genome.data.storage.parquet_store import ParquetHoldingsStore
from etf_genome.data.storage.sqlite_catalog import SqliteCatalog
from etf_genome.domain.models import FundMetadata


class LocalHoldingsStore:
    """Persist canonical holdings and query them back locally."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        parquet: ParquetHoldingsStore | None = None,
        catalog: SqliteCatalog | None = None,
        analytics: DuckDbAnalytics | None = None,
    ) -> None:
        settings.ensure_directories()
        self._parquet = parquet or ParquetHoldingsStore(settings.holdings_dir)
        self._catalog = catalog or SqliteCatalog(settings.sqlite_path)
        self._analytics = analytics or DuckDbAnalytics(settings.duckdb_path)
        self._catalog.initialize()

    @property
    def catalog(self) -> SqliteCatalog:
        return self._catalog

    @property
    def parquet(self) -> ParquetHoldingsStore:
        return self._parquet

    def write_holdings(self, frame: pl.DataFrame, metadata: FundMetadata) -> list[str]:
        """Store every snapshot in ``frame`` and index it in SQLite."""

        fund_ids = frame.get_column("fund_id").unique().to_list()
        if fund_ids != [metadata.fund_id]:
            raise StorageError(
                f"Frame fund ids {fund_ids} do not match metadata fund id {metadata.fund_id}"
            )
        paths = self._parquet.write(frame)
        self._catalog.upsert_fund(metadata)
        for path in paths:
            snapshot_date = date.fromisoformat(path.stem)
            subset = frame.filter(pl.col("snapshot_date") == snapshot_date)
            source_values = [
                value
                for value in subset.get_column("source").unique().to_list()
                if value is not None
            ]
            source = str(source_values[0]) if source_values else None
            self._catalog.upsert_snapshot(
                fund_id=metadata.fund_id,
                snapshot_date=snapshot_date,
                parquet_path=path,
                source=source,
                holding_count=subset.height,
            )
        return [str(path) for path in paths]

    def read_holdings(self, fund_id: str, snapshot_date: date) -> pl.DataFrame:
        return self._parquet.read(fund_id, snapshot_date)

    def summarize(self) -> tuple[pl.DataFrame, str]:
        """Return per-snapshot counts and the engine that produced them.

        DuckDB is the analytical engine. If Windows application control blocks
        the DuckDB native library, the same aggregation is computed with Polars
        and the engine name is ``polars_fallback``.
        """

        paths = self._parquet.list_files()
        if duckdb_import_error() is None:
            return self._analytics.summarize_holdings(paths), "duckdb"
        frames = [pl.read_parquet(path) for path in paths]
        if not frames:
            raise StorageError("Cannot summarize holdings because no Parquet files were written")
        combined = pl.concat(frames, how="vertical_relaxed")
        summary = (
            combined.group_by(["fund_id", "snapshot_date"])
            .agg(
                [
                    pl.len().alias("holding_count"),
                    pl.col("portfolio_weight").sum().alias("weight_sum"),
                ]
            )
            .sort(["fund_id", "snapshot_date"])
        )
        return summary, "polars_fallback"
