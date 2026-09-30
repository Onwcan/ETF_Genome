"""Canonical daily market bars and the provider boundary.

Feature code depends on these types, not on a vendor SDK. Only Twelve Data is
implemented. Other free providers can be added behind the same protocol later.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel, Field


class MarketInstrument(BaseModel):
    """A listed instrument. ``instrument_id`` is not a provider account id."""

    instrument_id: str
    ticker: str
    exchange: str | None = None
    currency: str | None = None


class MarketBar(BaseModel):
    """One daily session.

    Twelve Data's free ``time_series`` call with ``adjust=all`` returns a single
    OHLC series. Those values are stored in ``open``/``high``/``low``/``close``.
    ``adjusted_*`` stays null because the response has no second raw-or-adjusted
    series to copy. ``adjustment_mode`` records which request produced the series.
    """

    instrument_id: str
    ticker: str
    trading_date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    adjusted_open: float | None = None
    adjusted_high: float | None = None
    adjusted_low: float | None = None
    adjusted_close: float | None = None
    volume: float | None = None
    currency: str | None = None
    exchange: str | None = None
    provider: str
    adjustment_mode: str
    downloaded_at: datetime | None = None


class MarketDataResult(BaseModel):
    """Provider result. A missing key is ``not_configured``, not an exception."""

    status: str
    message: str
    provider: str
    adjustment_mode: str | None = None
    bars: list[MarketBar] = Field(default_factory=list)


class MarketDataProvider(Protocol):
    """Fetch daily bars. Do not fill sessions the provider did not return."""

    def fetch_daily_bars(
        self,
        instrument: MarketInstrument,
        start_date: date,
        end_date: date,
    ) -> MarketDataResult:
        """Return bars for the closed interval, ordered by trading date."""

        ...


QQQ_INSTRUMENT = MarketInstrument(
    instrument_id="ticker:QQQ",
    ticker="QQQ",
    exchange="NASDAQ",
    currency="USD",
)
ADJUSTMENT_ALL = "all"
PROVIDER_TWELVE_DATA = "twelvedata"
