"""DuckDB queries over local holdings Parquet files.

Connections are opened per query and closed immediately so Windows file locks
do not outlive the call.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import polars as pl

from etf_genome.data.storage.errors import StorageError

logger = logging.getLogger(__name__)

SUMMARY_SQL = """
SELECT
    fund_id,
    snapshot_date,
    COUNT(*) AS holding_count,
    SUM(portfolio_weight) AS weight_sum
FROM holdings
GROUP BY fund_id, snapshot_date
ORDER BY fund_id, snapshot_date
"""


class DuckDbAnalytics:
    """Run analytical SQL against a list of Parquet files."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def query_parquet(self, paths: list[Path], sql: str) -> pl.DataFrame:
        if not paths:
            raise StorageError("DuckDB query requires at least one Parquet file")
        missing = [path for path in paths if not path.is_file()]
        if missing:
            raise StorageError(f"Parquet file does not exist: {missing[0]}")
        duckdb = _import_duckdb()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(self.database_path))
        try:
            relation = connection.read_parquet([str(path) for path in paths])
            connection.register("holdings", relation)
            result = cast(pl.DataFrame, connection.execute(sql).pl())
        finally:
            connection.close()
        return result

    def summarize_holdings(self, paths: list[Path]) -> pl.DataFrame:
        return self.query_parquet(paths, SUMMARY_SQL)


def duckdb_import_error() -> str | None:
    """Return the DuckDB import error, or None when the native library loads."""

    try:
        _import_duckdb()
    except StorageError as exc:
        return str(exc)
    return None


def _import_duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:
        logger.warning("DuckDB native library did not load: %s", exc)
        raise StorageError(
            "DuckDB could not be loaded. Windows application control blocked the "
            "DuckDB native library on this machine, so analytical SQL cannot run "
            f"until that library is allowed. Original error: {exc}"
        ) from exc
    return duckdb
