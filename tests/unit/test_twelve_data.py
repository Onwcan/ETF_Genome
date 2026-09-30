"""Twelve Data parsing and QQQ bar storage. No network."""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.market_sync import sync_qqq_market
from etf_genome.data.sources.market import (
    QQQ_INSTRUMENT,
    MarketBar,
    MarketDataResult,
)
from etf_genome.data.sources.registry import MarketDataProviderRegistry
from etf_genome.data.sources.twelve_data import TwelveDataProvider
from etf_genome.data.storage.market_store import MarketStore


def _body(values: list[dict[str, str]]) -> dict[str, object]:
    return {
        "status": "ok",
        "meta": {"symbol": "QQQ", "exchange": "NASDAQ", "currency": "USD"},
        "values": values,
    }


def _bar(day: str, close: str = "100") -> dict[str, str]:
    return {
        "datetime": day,
        "open": "99",
        "high": "101",
        "low": "98",
        "close": close,
        "volume": "1000",
    }


def test_missing_api_key_does_not_call_the_provider() -> None:
    calls: list[object] = []

    def transport(*args: object) -> tuple[int, dict[str, object]]:
        calls.append(args)
        return 200, {}

    result = TwelveDataProvider(None, transport=transport).fetch_daily_bars(
        QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 5)
    )
    assert result.status == "NOT_CONFIGURED"
    assert calls == []
    assert "apikey" not in result.message


def test_successful_response_keeps_one_adjusted_series() -> None:
    def transport(*_args: object) -> tuple[int, dict[str, object]]:
        return 200, _body([_bar("2024-01-02", "207.8")])

    result = TwelveDataProvider("local-test-key", transport=transport).fetch_daily_bars(
        QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 5)
    )
    assert result.status == "ok"
    assert result.adjustment_mode == "all"
    assert result.bars[0].close == pytest.approx(207.8)
    assert result.bars[0].adjusted_close is None
    assert result.bars[0].exchange == "NASDAQ"
    assert result.bars[0].currency == "USD"


def test_invalid_and_rate_limited_responses() -> None:
    def invalid(*_args: object) -> tuple[int, dict[str, object]]:
        return 200, {"status": "error", "message": "bad"}

    def limited(*_args: object) -> tuple[int, dict[str, object]]:
        return 429, {"code": 429}

    provider = TwelveDataProvider("local-test-key", transport=invalid)
    assert (
        provider.fetch_daily_bars(QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 2)).status
        == "error"
    )
    limited_provider = TwelveDataProvider("local-test-key", transport=limited)
    assert (
        limited_provider.fetch_daily_bars(QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 2)).status
        == "rate_limit"
    )


def test_timeout_does_not_expose_the_request() -> None:
    def transport(*_args: object) -> tuple[int, dict[str, object]]:
        raise httpx.TimeoutException("https://api.twelvedata.com/time_series?apikey=SECRET")

    result = TwelveDataProvider("SECRET", transport=transport).fetch_daily_bars(
        QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 2)
    )
    assert result.status == "timeout"
    assert "SECRET" not in result.message


def test_empty_date_window_is_not_a_failure() -> None:
    def transport(*_args: object) -> tuple[int, dict[str, object]]:
        return 400, {
            "status": "error",
            "code": 400,
            "message": (
                "No data is available on the specified dates. "
                "Try setting different start/end dates."
            ),
        }

    result = TwelveDataProvider("local-test-key", transport=transport).fetch_daily_bars(
        QQQ_INSTRUMENT, date(2026, 9, 19), date(2026, 9, 21)
    )
    assert result.status == "ok"
    assert result.bars == []


def test_malformed_numbers_and_duplicate_dates() -> None:
    def malformed(*_args: object) -> tuple[int, dict[str, object]]:
        bar = _bar("2024-01-02")
        bar["close"] = "not-a-price"
        return 200, _body([bar])

    def duplicates(*_args: object) -> tuple[int, dict[str, object]]:
        return 200, _body(
            [_bar("2024-01-02", "10"), _bar("2024-01-02", "11"), _bar("2024-01-03", "12")]
        )

    bad = TwelveDataProvider("local-test-key", transport=malformed)
    assert (
        bad.fetch_daily_bars(QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 3)).status == "error"
    )
    good = TwelveDataProvider("local-test-key", transport=duplicates)
    result = good.fetch_daily_bars(QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 3))
    assert [bar.trading_date.isoformat() for bar in result.bars] == ["2024-01-02", "2024-01-03"]
    assert result.bars[0].close == pytest.approx(10)


def test_incremental_upsert_is_idempotent(settings: AppSettings) -> None:
    store = MarketStore(settings)
    first = _stored_bar(date(2024, 1, 2), 10)
    before, added = store.upsert([first])
    assert (before, added) == (0, 1)
    _before, added_again = store.upsert([first, _stored_bar(date(2024, 1, 3), 11)])
    assert added_again == 1
    assert store.read().height == 2
    _before, none_added = store.upsert([_stored_bar(date(2024, 1, 3), 11)])
    assert none_added == 0
    assert store.read().height == 2


def test_failed_sync_preserves_cached_bars(settings: AppSettings) -> None:
    store = MarketStore(settings)
    store.upsert([_stored_bar(date(2024, 1, 2), 10)])

    class Broken:
        def fetch_daily_bars(self, instrument: object, start: date, end: date) -> MarketDataResult:
            return MarketDataResult(
                status="error",
                message="Twelve Data returned an error.",
                provider="twelvedata",
                adjustment_mode="all",
            )

    result = sync_qqq_market(settings, Broken(), now=datetime(2024, 6, 3, 22, tzinfo=UTC))
    assert result.status == "error"
    assert result.new_bars == 0
    frame = store.read()
    assert frame.height == 1
    assert frame.get_column("close").item() == pytest.approx(10)


def test_registry_reports_missing_twelve_data_key() -> None:
    registry = MarketDataProviderRegistry()
    assert "twelvedata" in registry.implemented()
    assert "tiingo" in registry.implemented()
    assert (
        registry.create("twelvedata")
        .fetch_daily_bars(QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 2))
        .status
        == "NOT_CONFIGURED"
    )


def _stored_bar(trading_date: date, close: float) -> MarketBar:
    return MarketBar(
        instrument_id="ticker:QQQ",
        ticker="QQQ",
        trading_date=trading_date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1,
        currency="USD",
        exchange="NASDAQ",
        provider="twelvedata",
        adjustment_mode="all",
        downloaded_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
