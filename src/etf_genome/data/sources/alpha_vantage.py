"""Alpha Vantage free daily bars, unadjusted only.

Checked on 2026-09-22. The free key allows about 25 requests per day.
``TIME_SERIES_DAILY_ADJUSTED`` is marked premium, so this provider never
calls it. The free series is raw OHLC. It is not a training source.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx

from etf_genome.data.sources.market import MarketBar, MarketDataResult, MarketInstrument

PROVIDER = "alphavantage"
ADJUSTMENT = "none"
_FUNCTION = "TIME_SERIES_DAILY"


class AlphaVantageProvider:
    """Unadjusted daily bars from the free ``TIME_SERIES_DAILY`` function."""

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout: float = 30.0,
        transport: Callable[..., tuple[int, Any]] | None = None,
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self._timeout = timeout
        self._transport = transport or _http_get

    def fetch_daily_bars(
        self,
        instrument: MarketInstrument,
        start_date: date,
        end_date: date,
    ) -> MarketDataResult:
        if not self._api_key:
            return _error(
                "NOT_CONFIGURED",
                "Alpha Vantage is not configured. Set ETF_GENOME_ALPHA_VANTAGE_API_KEY.",
            )
        if end_date < start_date:
            return _error("error", "Market data end date is before the start date.")
        try:
            status_code, body = self._transport(
                "https://www.alphavantage.co/query",
                {
                    "function": _FUNCTION,
                    "symbol": instrument.ticker,
                    "outputsize": "full",
                    "datatype": "json",
                    "apikey": self._api_key,
                },
                self._timeout,
            )
        except httpx.TimeoutException:
            return _error("timeout", "Alpha Vantage request timed out.")
        except httpx.HTTPError:
            return _error("offline", "Alpha Vantage request failed.")
        return _parse(
            instrument,
            status_code,
            body,
            start_date=start_date,
            end_date=end_date,
            downloaded_at=datetime.now(UTC),
        )


def _http_get(url: str, params: dict[str, str], timeout: float) -> tuple[int, Any]:
    response = httpx.get(url, params=params, timeout=timeout, follow_redirects=False)
    try:
        payload = response.json()
    except ValueError:
        payload = {"Error Message": "Alpha Vantage response was not JSON"}
    if not isinstance(payload, dict):
        payload = {"Error Message": "Alpha Vantage response was not an object"}
    return response.status_code, payload


def _parse(
    instrument: MarketInstrument,
    status_code: int,
    body: dict[str, Any],
    *,
    start_date: date,
    end_date: date,
    downloaded_at: datetime,
) -> MarketDataResult:
    if "Note" in body or "Information" in body:
        return _error("rate_limit", "Alpha Vantage rate limit reached.")
    if status_code in {401, 403} or "Error Message" in body:
        return _error("error", "Alpha Vantage request failed.")
    if status_code >= 500:
        return _error("server", "Alpha Vantage returned a server error.")
    series = body.get("Time Series (Daily)")
    if not isinstance(series, dict):
        return _error("error", "Alpha Vantage response did not include bars.")
    bars: list[MarketBar] = []
    seen: set[date] = set()
    for raw_date, item in series.items():
        if not isinstance(raw_date, str) or not isinstance(item, dict):
            return _error("error", "Alpha Vantage returned a malformed bar.")
        try:
            trading_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            return _error("error", "Alpha Vantage returned a malformed bar.")
        if trading_date < start_date or trading_date > end_date or trading_date in seen:
            continue
        bar = _bar(instrument, trading_date, item, downloaded_at)
        if bar is None:
            return _error("error", "Alpha Vantage returned a malformed bar.")
        seen.add(trading_date)
        bars.append(bar)
    bars.sort(key=lambda item: item.trading_date)
    return MarketDataResult(
        status="ok",
        message=f"Received {len(bars)} daily bars.",
        provider=PROVIDER,
        adjustment_mode=ADJUSTMENT,
        bars=bars,
    )


def _bar(
    instrument: MarketInstrument,
    trading_date: date,
    item: dict[str, Any],
    downloaded_at: datetime,
) -> MarketBar | None:
    try:
        open_ = float(item["1. open"])
        high = float(item["2. high"])
        low = float(item["3. low"])
        close = float(item["4. close"])
        volume = float(item["5. volume"]) if item.get("5. volume") not in {None, ""} else None
    except (KeyError, TypeError, ValueError):
        return None
    if high < low or close < 0:
        return None
    return MarketBar(
        instrument_id=instrument.instrument_id,
        ticker=instrument.ticker,
        trading_date=trading_date,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        currency=instrument.currency,
        exchange=instrument.exchange,
        provider=PROVIDER,
        adjustment_mode=ADJUSTMENT,
        downloaded_at=downloaded_at,
    )


def _error(status: str, message: str) -> MarketDataResult:
    return MarketDataResult(
        status=status,
        message=message,
        provider=PROVIDER,
        adjustment_mode=ADJUSTMENT,
    )
