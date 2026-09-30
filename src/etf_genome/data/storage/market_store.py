"""Parquet store for one daily price series, plus SQLite sync metadata."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.market import ADJUSTMENT_ALL, PROVIDER_TWELVE_DATA, MarketBar
from etf_genome.data.storage.errors import StorageError

_COLUMNS = [
    "instrument_id",
    "ticker",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "volume",
    "currency",
    "exchange",
    "provider",
    "adjustment_mode",
    "downloaded_at",
]


class MarketStore:
    """Upsert daily bars without duplicating trading dates."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        provider: str = PROVIDER_TWELVE_DATA,
        adjustment_mode: str = ADJUSTMENT_ALL,
    ) -> None:
        self._settings = settings
        self.provider = provider
        self.adjustment_mode = adjustment_mode
        filename = f"{provider}_{adjustment_mode}.parquet"
        self.path = settings.processed_dir / "market" / "ticker_QQQ" / filename
        self._catalog = settings.sqlite_path

    def read(self) -> pl.DataFrame:
        if not self.path.is_file():
            return pl.DataFrame(schema={column: pl.Utf8 for column in _COLUMNS}).clear()
        frame = pl.read_parquet(self.path)
        if "trading_date" in frame.columns and frame.schema["trading_date"] != pl.Date:
            frame = frame.with_columns(pl.col("trading_date").cast(pl.Date))
        return frame.sort("trading_date")

    def upsert(self, bars: list[MarketBar]) -> tuple[int, int]:
        """Return ``(existing_before, new_or_replaced)``."""

        incoming = _frame(bars)
        if incoming.is_empty():
            current = self.read()
            return current.height, 0
        current = self.read()
        before = current.height
        existing = set(current.get_column("trading_date").to_list()) if before else set()
        incoming_dates = incoming.get_column("trading_date").to_list()
        added = sum(1 for value in incoming_dates if value not in existing)
        if current.is_empty():
            combined = incoming
        else:
            combined = pl.concat([current, incoming], how="vertical_relaxed")
        combined = combined.unique(subset=["trading_date"], keep="last").sort("trading_date")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".parquet.tmp")
        combined.write_parquet(temporary)
        temporary.replace(self.path)
        self._write_meta(combined)
        return before, added

    def latest_date(self) -> date | None:
        frame = self.read()
        if frame.is_empty():
            return None
        value = frame.get_column("trading_date").max()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return None

    def _write_meta(self, frame: pl.DataFrame) -> None:
        earliest = frame.get_column("trading_date").min()
        latest = frame.get_column("trading_date").max()
        self._catalog.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._catalog)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_sync (
                    provider TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    adjustment_mode TEXT NOT NULL,
                    earliest_date TEXT,
                    latest_date TEXT,
                    bar_count INTEGER NOT NULL,
                    last_success_at TEXT,
                    last_error TEXT,
                    parquet_path TEXT,
                    PRIMARY KEY (provider, instrument_id, adjustment_mode)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO market_sync (
                    provider, instrument_id, adjustment_mode, earliest_date, latest_date,
                    bar_count, last_success_at, last_error, parquet_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(provider, instrument_id, adjustment_mode) DO UPDATE SET
                    earliest_date = excluded.earliest_date,
                    latest_date = excluded.latest_date,
                    bar_count = excluded.bar_count,
                    last_success_at = excluded.last_success_at,
                    last_error = NULL,
                    parquet_path = excluded.parquet_path
                """,
                (
                    self.provider,
                    "ticker:QQQ",
                    self.adjustment_mode,
                    _iso(earliest),
                    _iso(latest),
                    frame.height,
                    datetime.now(UTC).isoformat(),
                    str(self.path),
                ),
            )
            connection.commit()
        finally:
            connection.close()


def _frame(bars: list[MarketBar]) -> pl.DataFrame:
    if not bars:
        return pl.DataFrame()
    return pl.DataFrame([bar.model_dump() for bar in bars]).with_columns(
        pl.col("trading_date").cast(pl.Date),
        pl.col("downloaded_at").cast(pl.Datetime(time_zone="UTC")),
    )


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def require_market_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        raise StorageError("No local market bars are stored.")
    return frame
