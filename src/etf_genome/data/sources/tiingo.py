"""Tiingo Starter free daily bars.

The free plan, checked on 2026-09-22, includes ETF end-of-day history and
separate raw and split/dividend-adjusted fields. The API token is not stored
on results or in error text. Tiingo is optional; Twelve Data remains the
training source.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx

from etf_genome.data.sources.market import MarketBar, MarketDataResult, MarketInstrument

PROVIDER = "tiingo"
ADJUSTMENT = "raw_and_split_dividend"


class TiingoProvider:
    """Daily bars from ``GET /tiingo/daily/{ticker}/prices``."""

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
                "Tiingo is not configured. Set ETF_GENOME_TIINGO_API_KEY.",
            )
        if end_date < start_date:
            return _error("error", "Market data end date is before the start date.")
        try:
            status_code, body = self._transport(
                f"https://api.tiingo.com/tiingo/daily/{instrument.ticker}/prices",
                {
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "resampleFreq": "daily",
                    "format": "json",
                },
                {"Authorization": f"Token {self._api_key}"},
                self._timeout,
            )
        except httpx.TimeoutException:
            return _error("timeout", "Tiingo request timed out.")
        except httpx.HTTPError:
            return _error("offline", "Tiingo request failed.")
        return _parse(instrument, status_code, body, downloaded_at=datetime.now(UTC))


def _http_get(
    url: str,
    params: dict[str, str],
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, Any]:
    response = httpx.get(
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": "Tiingo response was not JSON"}
    return response.status_code, payload


def _parse(
    instrument: MarketInstrument,
    status_code: int,
    body: Any,
    *,
    downloaded_at: datetime,
) -> MarketDataResult:
    if status_code == 429:
        return _error("rate_limit", "Tiingo rate limit reached.")
    if status_code in {401, 403}:
        return _error("rejected", "Tiingo rejected the request.")
    if status_code >= 500:
        return _error("server", "Tiingo returned a server error.")
    if status_code != 200 or not isinstance(body, list):
        return _error("error", "Tiingo request failed.")
    bars: list[MarketBar] = []
    seen: set[date] = set()
    for item in body:
        if not isinstance(item, dict):
            return _error("error", "Tiingo returned a malformed bar.")
        bar = _bar(instrument, item, downloaded_at)
        if bar is None:
            return _error("error", "Tiingo returned a malformed bar.")
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
    raw_date = item.get("date")
    if not isinstance(raw_date, str) or len(raw_date) < 10:
        return None
    try:
        trading_date = date.fromisoformat(raw_date[:10])
        open_ = _float(item.get("open"))
        high = _float(item.get("high"))
        low = _float(item.get("low"))
        close = _float(item.get("close"))
    except ValueError:
        return None
    if open_ is None or high is None or low is None or close is None or high < low:
        return None
    try:
        adjusted_open = _optional(item.get("adjOpen"))
        adjusted_high = _optional(item.get("adjHigh"))
        adjusted_low = _optional(item.get("adjLow"))
        adjusted_close = _optional(item.get("adjClose"))
        volume = _optional(item.get("volume"))
    except ValueError:
        return None
    return MarketBar(
        instrument_id=instrument.instrument_id,
        ticker=instrument.ticker,
        trading_date=trading_date,
        open=open_,
        high=high,
        low=low,
        close=close,
        adjusted_open=adjusted_open,
        adjusted_high=adjusted_high,
        adjusted_low=adjusted_low,
        adjusted_close=adjusted_close,
        volume=volume,
        currency=instrument.currency,
        exchange=instrument.exchange,
        provider=PROVIDER,
        adjustment_mode=ADJUSTMENT,
        downloaded_at=downloaded_at,
    )


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return _numeric(value)


def _optional(value: object) -> float | None:
    if value is None or value == "":
        return None
    return _numeric(value)


def _numeric(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Tiingo field is not numeric.")
    return float(value)


def _error(status: str, message: str) -> MarketDataResult:
    return MarketDataResult(
        status=status,
        message=message,
        provider=PROVIDER,
        adjustment_mode=ADJUSTMENT,
    )
