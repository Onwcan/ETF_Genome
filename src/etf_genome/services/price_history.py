"""Authoritative close history for a later chart. No plotting library."""

from __future__ import annotations

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.storage.market_store import MarketStore


def authoritative_closes(settings: AppSettings) -> pl.DataFrame:
    """Return the Twelve Data training series, not a mixed provider file."""

    frame = MarketStore(settings).read()
    if frame.is_empty():
        return frame
    columns = ["trading_date", "close", "provider", "adjustment_mode"]
    return frame.select([column for column in columns if column in frame.columns])
