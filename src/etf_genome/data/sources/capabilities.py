"""What each market provider can actually supply.

Capabilities are explicit because a free daily feed is not the same thing as
a split-and-dividend history long enough to train on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ProviderCapabilities:
    name: str
    classification: str
    supports_daily_bars: bool
    supports_adjusted_prices: bool
    supports_dividends: bool
    supports_splits: bool
    supports_etfs: bool
    historical_start: date | None
    requires_api_key: bool
    official_api: bool
    suitable_for_training: bool
    notes: str


TWELVE_DATA = ProviderCapabilities(
    name="twelvedata",
    classification="PRIMARY_FREE",
    supports_daily_bars=True,
    supports_adjusted_prices=True,
    supports_dividends=True,
    supports_splits=True,
    supports_etfs=True,
    historical_start=date(2019, 1, 1),
    requires_api_key=True,
    official_api=True,
    suitable_for_training=True,
    notes="Basic free time_series with adjust=all. One OHLC series, stored in close.",
)
TIINGO = ProviderCapabilities(
    name="tiingo",
    classification="SECONDARY_FREE",
    supports_daily_bars=True,
    supports_adjusted_prices=True,
    supports_dividends=True,
    supports_splits=True,
    supports_etfs=True,
    historical_start=date(1962, 1, 1),
    requires_api_key=True,
    official_api=True,
    suitable_for_training=False,
    notes="Starter free has long ETF history. Optional. Not mixed into the training file.",
)
MASSIVE = ProviderCapabilities(
    name="massive",
    classification="SECONDARY_FREE",
    supports_daily_bars=True,
    supports_adjusted_prices=True,
    supports_dividends=False,
    supports_splits=True,
    supports_etfs=True,
    historical_start=None,
    requires_api_key=True,
    official_api=True,
    suitable_for_training=False,
    notes="Stocks Basic free is about two years of split-adjusted end-of-day bars.",
)
ALPHA_VANTAGE = ProviderCapabilities(
    name="alphavantage",
    classification="FALLBACK_FREE",
    supports_daily_bars=True,
    supports_adjusted_prices=False,
    supports_dividends=False,
    supports_splits=False,
    supports_etfs=True,
    historical_start=date(2000, 1, 1),
    requires_api_key=True,
    official_api=True,
    suitable_for_training=False,
    notes="Free TIME_SERIES_DAILY is unadjusted. The adjusted endpoint is premium and unused.",
)
YAHOO = ProviderCapabilities(
    name="yahoo",
    classification="UNOFFICIAL_FALLBACK",
    supports_daily_bars=True,
    supports_adjusted_prices=True,
    supports_dividends=False,
    supports_splits=False,
    supports_etfs=True,
    historical_start=date(1999, 3, 10),
    requires_api_key=False,
    official_api=False,
    suitable_for_training=False,
    notes="Public chart endpoint, not an official API and not the yfinance package.",
)
STOOQ = ProviderCapabilities(
    name="stooq",
    classification="UNSUITABLE",
    supports_daily_bars=False,
    supports_adjusted_prices=False,
    supports_dividends=False,
    supports_splits=False,
    supports_etfs=True,
    historical_start=None,
    requires_api_key=True,
    official_api=False,
    suitable_for_training=False,
    notes="CAPTCHA key required as of 2026-09-22. Redistribution prohibited. Not enabled.",
)

CATALOG: dict[str, ProviderCapabilities] = {
    item.name: item for item in (TWELVE_DATA, TIINGO, MASSIVE, ALPHA_VANTAGE, YAHOO, STOOQ)
}
