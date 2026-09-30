"""Twelve Data Basic free daily bars.

The API key is read from configuration at call time and is not stored on the
result, in exceptions, or in log messages.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx

from etf_genome.data.sources.market import (
    ADJUSTMENT_ALL,
    PROVIDER_TWELVE_DATA,
    MarketBar,
    MarketDataResult,
    MarketInstrument,
)

_URL = "https://api.twelvedata.com/time_series"


class TwelveDataProvider:
    """Daily OHLCV from ``GET /time_series`` with ``adjust=all``."""

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout: float = 30.0,
        transport: Callable[..., tuple[int, dict[str, Any]]] | None = None,
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
            return MarketDataResult(
                status="NOT_CONFIGURED",
                message="Twelve Data is not configured. Set ETF_GENOME_TWELVE_DATA_API_KEY.",
                provider=PROVIDER_TWELVE_DATA,
            )
        if end_date < start_date:
            return MarketDataResult(
                status="error",
                message="Market data end date is before the start date.",
                provider=PROVIDER_TWELVE_DATA,
                adjustment_mode=ADJUSTMENT_ALL,
            )
        try:
            status_code, body = self._transport(
                _URL,
                {
                    "symbol": instrument.ticker,
                    "interval": "1day",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "adjust": ADJUSTMENT_ALL,
                    "order": "ASC",
                    "outputsize": "5000",
                    "format": "JSON",
                    "timezone": "America/New_York",
                    "apikey": self._api_key,
                },
                self._timeout,
            )
        except httpx.TimeoutException:
            return _error("timeout", "Twelve Data request timed out.")
        except httpx.HTTPError:
            return _error("offline", "Twelve Data request failed.")
        return _parse_time_series(
            instrument,
            status_code,
            body,
            downloaded_at=datetime.now(UTC),
        )


def _http_get(url: str, params: dict[str, str], timeout: float) -> tuple[int, dict[str, Any]]:
    response = httpx.get(url, params=params, timeout=timeout, follow_redirects=False)
    try:
        payload = response.json()
    except ValueError:
        payload = {"status": "error", "message": "Twelve Data response was not JSON"}
    if not isinstance(payload, dict):
        payload = {"status": "error", "message": "Twelve Data response was not an object"}
    return response.status_code, payload


def _parse_time_series(
    instrument: MarketInstrument,
    status_code: int,
    body: dict[str, Any],
    *,
    downloaded_at: datetime,
) -> MarketDataResult:
    if status_code == 429 or body.get("code") in {429, "429"}:
        return _error("rate_limit", "Twelve Data rate limit reached.")
    if status_code in {401, 403} or body.get("code") in {401, 403, "401", "403"}:
        return _error("rejected", "Twelve Data rejected the request.")
    if _no_bars(body):
        return MarketDataResult(
            status="ok",
            message="Received 0 daily bars.",
            provider=PROVIDER_TWELVE_DATA,
            adjustment_mode=ADJUSTMENT_ALL,
        )
    if body.get("status") == "error":
        return _error("error", "Twelve Data returned an error.")
    if status_code >= 500:
        return _error("server", "Twelve Data returned a server error.")
    if status_code != 200:
        return _error("error", "Twelve Data request failed.")
    values = body.get("values")
    if not isinstance(values, list):
        return _error("error", "Twelve Data response did not include bars.")
    raw_meta = body.get("meta")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    exchange = _text(meta.get("exchange")) or instrument.exchange
    currency = _text(meta.get("currency")) or instrument.currency
    bars: list[MarketBar] = []
    seen: set[date] = set()
    for item in values:
        if not isinstance(item, dict):
            return _error("error", "Twelve Data returned a malformed bar.")
        bar = _bar(instrument, item, exchange, currency, downloaded_at)
        if bar is None:
            return _error("error", "Twelve Data returned a malformed bar.")
        if bar.trading_date in seen:
            continue
        seen.add(bar.trading_date)
        bars.append(bar)
    bars.sort(key=lambda item: item.trading_date)
    return MarketDataResult(
        status="ok",
        message=f"Received {len(bars)} daily bars.",
        provider=PROVIDER_TWELVE_DATA,
        adjustment_mode=ADJUSTMENT_ALL,
        bars=bars,
    )


def _bar(
    instrument: MarketInstrument,
    item: dict[str, Any],
    exchange: str | None,
    currency: str | None,
    downloaded_at: datetime,
) -> MarketBar | None:
    raw_date = _text(item.get("datetime"))
    if raw_date is None:
        return None
    try:
        trading_date = date.fromisoformat(raw_date[:10])
    except ValueError:
        return None
    try:
        open_ = _optional_float(item.get("open"))
        high = _optional_float(item.get("high"))
        low = _optional_float(item.get("low"))
        close = _optional_float(item.get("close"))
        volume = _optional_float(item.get("volume"))
    except ValueError:
        return None
    if close is None or open_ is None or high is None or low is None:
        return None
    if high < low or close < 0 or open_ < 0:
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
        currency=currency,
        exchange=exchange,
        provider=PROVIDER_TWELVE_DATA,
        adjustment_mode=ADJUSTMENT_ALL,
        downloaded_at=downloaded_at,
    )


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Twelve Data field is not numeric.")
    return float(value)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _no_bars(body: dict[str, Any]) -> bool:
    message = body.get("message")
    return isinstance(message, str) and "no data is available" in message.lower()


def _error(status: str, message: str) -> MarketDataResult:
    return MarketDataResult(
        status=status,
        message=message,
        provider=PROVIDER_TWELVE_DATA,
        adjustment_mode=ADJUSTMENT_ALL,
    )
