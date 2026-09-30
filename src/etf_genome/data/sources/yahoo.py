"""Unofficial Yahoo Finance chart fallback.

This is not an official Yahoo API and it is not a yfinance dependency.
Checked on 2026-09-22: the public chart endpoint returned QQQ daily bars
with a separate ``adjclose`` field and no API key. Schema changes are
treated as provider errors. Training continues to use the Twelve Data file.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx

from etf_genome.data.sources.market import MarketBar, MarketDataResult, MarketInstrument

PROVIDER = "yahoo"
ADJUSTMENT = "raw_ohlc_plus_adjclose"


class YahooFinanceProvider:
    """Daily bars from Yahoo's public chart endpoint. Unofficial."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        transport: Callable[..., tuple[int, Any]] | None = None,
    ) -> None:
        self._timeout = timeout
        self._transport = transport or _http_get

    def fetch_daily_bars(
        self,
        instrument: MarketInstrument,
        start_date: date,
        end_date: date,
    ) -> MarketDataResult:
        if end_date < start_date:
            return _error("error", "Market data end date is before the start date.")
        start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
        end = datetime(end_date.year, end_date.month, end_date.day, 23, 59, tzinfo=UTC)
        try:
            status_code, body = self._transport(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{instrument.ticker}",
                {
                    "interval": "1d",
                    "period1": str(int(start.timestamp())),
                    "period2": str(int(end.timestamp())),
                    "events": "div,splits",
                    "includeAdjustedClose": "true",
                },
                self._timeout,
            )
        except httpx.TimeoutException:
            return _error("timeout", "Yahoo Finance request timed out.")
        except httpx.HTTPError:
            return _error("offline", "Yahoo Finance request failed.")
        return _parse(instrument, status_code, body, downloaded_at=datetime.now(UTC))


def _http_get(url: str, params: dict[str, str], timeout: float) -> tuple[int, Any]:
    response = httpx.get(
        url,
        params=params,
        headers={"User-Agent": "ETFGenome research"},
        timeout=timeout,
        follow_redirects=False,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"chart": {"error": {"description": "not json"}}}
    if not isinstance(payload, dict):
        payload = {"chart": {"error": {"description": "not an object"}}}
    return response.status_code, payload


def _parse(
    instrument: MarketInstrument,
    status_code: int,
    body: dict[str, Any],
    *,
    downloaded_at: datetime,
) -> MarketDataResult:
    if status_code == 429:
        return _error("rate_limit", "Yahoo Finance rate limit reached.")
    if status_code >= 500:
        return _error("server", "Yahoo Finance returned a server error.")
    if status_code != 200:
        return _error("error", "Yahoo Finance request failed.")
    chart = body.get("chart")
    if not isinstance(chart, dict):
        return _error("error", "Yahoo Finance response did not include bars.")
    if chart.get("error"):
        return _error("error", "Yahoo Finance request failed.")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return _error("error", "Yahoo Finance response did not include bars.")
    result = results[0]
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        return _error("error", "Yahoo Finance response did not include bars.")
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
        return _error("error", "Yahoo Finance response did not include bars.")
    quote = quotes[0]
    adjusted = _adjusted_list(indicators.get("adjclose"))
    raw_meta = result.get("meta")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    raw_currency = meta.get("currency")
    currency = raw_currency if isinstance(raw_currency, str) else instrument.currency
    raw_exchange = meta.get("exchangeName")
    exchange = raw_exchange if isinstance(raw_exchange, str) else instrument.exchange
    bars: list[MarketBar] = []
    seen: set[date] = set()
    for index, raw_time in enumerate(timestamps):
        if not isinstance(raw_time, (int, float)):
            return _error("error", "Yahoo Finance returned a malformed bar.")
        trading_date = datetime.fromtimestamp(raw_time, tz=UTC).date()
        if trading_date in seen:
            continue
        bar = _bar(
            instrument,
            trading_date,
            quote,
            adjusted,
            index,
            currency,
            exchange,
            downloaded_at,
        )
        if bar is None:
            continue
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


def _adjusted_list(value: object) -> list[object] | None:
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        return None
    series = value[0].get("adjclose")
    return series if isinstance(series, list) else None


def _bar(
    instrument: MarketInstrument,
    trading_date: date,
    quote: dict[str, Any],
    adjusted: list[object] | None,
    index: int,
    currency: str | None,
    exchange: str | None,
    downloaded_at: datetime,
) -> MarketBar | None:
    try:
        open_ = _at(quote.get("open"), index)
        high = _at(quote.get("high"), index)
        low = _at(quote.get("low"), index)
        close = _at(quote.get("close"), index)
        volume = _at(quote.get("volume"), index)
        adjusted_close = None if adjusted is None else _at(adjusted, index)
    except (TypeError, ValueError, IndexError):
        return None
    if open_ is None or high is None or low is None or close is None or high < low:
        return None
    return MarketBar(
        instrument_id=instrument.instrument_id,
        ticker=instrument.ticker,
        trading_date=trading_date,
        open=open_,
        high=high,
        low=low,
        close=close,
        adjusted_close=adjusted_close,
        volume=volume,
        currency=currency,
        exchange=exchange,
        provider=PROVIDER,
        adjustment_mode=ADJUSTMENT,
        downloaded_at=downloaded_at,
    )


def _at(values: object, index: int) -> float | None:
    if not isinstance(values, list) or index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _error(status: str, message: str) -> MarketDataResult:
    return MarketDataResult(
        status=status,
        message=message,
        provider=PROVIDER,
        adjustment_mode=ADJUSTMENT,
    )
