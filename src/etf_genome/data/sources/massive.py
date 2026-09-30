"""Massive Stocks Basic daily aggregates.

Checked on 2026-09-22. The free Stocks Basic plan publishes end-of-day bars
with about two years of history and five calls per minute. That is too short
for the 2019 training window, so this provider is for recent comparison only.
``adjusted=true`` on the aggregates endpoint is split adjustment, not a
dividend total-return series. Paid history tiers are not requested.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from etf_genome.data.sources.market import MarketBar, MarketDataResult, MarketInstrument

PROVIDER = "massive"
ADJUSTMENT = "splits"
_EASTERN = ZoneInfo("America/New_York")


class MassiveProvider:
    """Daily bars from ``GET /v2/aggs/ticker/{ticker}/range/1/day``."""

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
                "Massive is not configured. Set ETF_GENOME_MASSIVE_API_KEY.",
            )
        if end_date < start_date:
            return _error("error", "Market data end date is before the start date.")
        url = (
            "https://api.massive.com/v2/aggs/ticker/"
            f"{instrument.ticker}/range/1/day/{start_date.isoformat()}/{end_date.isoformat()}"
        )
        try:
            status_code, body = self._transport(
                url,
                {"adjusted": "true", "sort": "asc", "limit": "50000"},
                self._api_key,
                self._timeout,
            )
        except httpx.TimeoutException:
            return _error("timeout", "Massive request timed out.")
        except httpx.HTTPError:
            return _error("offline", "Massive request failed.")
        return _parse(instrument, status_code, body, downloaded_at=datetime.now(UTC))


def _http_get(
    url: str,
    params: dict[str, str],
    api_key: str,
    timeout: float,
) -> tuple[int, Any]:
    response = httpx.get(
        url,
        params={**params, "apiKey": api_key},
        timeout=timeout,
        follow_redirects=False,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"status": "ERROR"}
    if not isinstance(payload, dict):
        payload = {"status": "ERROR"}
    return response.status_code, payload


def _parse(
    instrument: MarketInstrument,
    status_code: int,
    body: dict[str, Any],
    *,
    downloaded_at: datetime,
) -> MarketDataResult:
    if status_code == 429:
        return _error("rate_limit", "Massive rate limit reached.")
    if status_code in {401, 403}:
        return _error("rejected", "Massive rejected the request.")
    status = str(body.get("status", "")).upper()
    if status_code >= 500 or status == "ERROR":
        return _error("error", "Massive request failed.")
    if status_code != 200:
        return _error("error", "Massive request failed.")
    results = body.get("results")
    if results is None:
        return MarketDataResult(
            status="ok",
            message="Received 0 daily bars.",
            provider=PROVIDER,
            adjustment_mode=ADJUSTMENT,
        )
    if not isinstance(results, list):
        return _error("error", "Massive returned a malformed response.")
    bars: list[MarketBar] = []
    seen: set[date] = set()
    for item in results:
        if not isinstance(item, dict):
            return _error("error", "Massive returned a malformed bar.")
        bar = _bar(instrument, item, downloaded_at)
        if bar is None:
            return _error("error", "Massive returned a malformed bar.")
        if bar.trading_date in seen:
            continue
        seen.add(bar.trading_date)
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
    item: dict[str, Any],
    downloaded_at: datetime,
) -> MarketBar | None:
    raw_time = item.get("t")
    if not isinstance(raw_time, (int, float)):
        return None
    trading_date = datetime.fromtimestamp(raw_time / 1000, tz=UTC).astimezone(_EASTERN).date()
    try:
        open_ = float(item["o"])
        high = float(item["h"])
        low = float(item["l"])
        close = float(item["c"])
        volume = float(item["v"]) if item.get("v") is not None else None
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
