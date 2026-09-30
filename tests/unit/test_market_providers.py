"""Provider registry, canonical conversion, and comparison. No network."""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.alpha_vantage import AlphaVantageProvider
from etf_genome.data.sources.comparison import compare_sessions, continuity_close
from etf_genome.data.sources.market import QQQ_INSTRUMENT
from etf_genome.data.sources.massive import MassiveProvider
from etf_genome.data.sources.registry import MarketDataProviderRegistry, health_from_status
from etf_genome.data.sources.tiingo import TiingoProvider
from etf_genome.data.sources.yahoo import YahooFinanceProvider
from etf_genome.data.storage.market_store import MarketStore
from etf_genome.services.app_status import build_application_status


def test_registry_keeps_twelve_data_authoritative(settings: AppSettings) -> None:
    registry = MarketDataProviderRegistry()
    tuned = settings.model_copy(update={"preferred_market_provider": "yahoo"})
    assert registry.authoritative_name() == "twelvedata"
    assert registry.capabilities("twelvedata").suitable_for_training is True
    assert registry.capabilities("yahoo").suitable_for_training is False
    assert registry.capabilities("tiingo").classification == "SECONDARY_FREE"
    assert registry.is_configured("tiingo", tuned) is False
    assert registry.is_configured("yahoo", tuned) is True
    assert (
        registry.create("tiingo", tuned)
        .fetch_daily_bars(QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 2))
        .status
        == "NOT_CONFIGURED"
    )


def test_stooq_is_not_enabled() -> None:
    registry = MarketDataProviderRegistry()
    assert registry.capabilities("stooq").classification == "UNSUITABLE"
    try:
        registry.create("stooq")
    except ValueError as exc:
        assert "not an enabled" in str(exc)
    else:
        raise AssertionError("stooq should not be constructed")


def test_tiingo_keeps_raw_and_adjusted_fields() -> None:
    def transport(*_args: object) -> tuple[int, object]:
        return 200, [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "volume": 10,
                "adjOpen": 50,
                "adjHigh": 55,
                "adjLow": 45,
                "adjClose": 52,
            }
        ]

    result = TiingoProvider("local-test-key", transport=transport).fetch_daily_bars(
        QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 3)
    )
    assert result.status == "ok"
    assert result.bars[0].close == 105
    assert result.bars[0].adjusted_close == 52
    assert result.adjustment_mode == "raw_and_split_dividend"


def test_massive_missing_key_and_split_adjustment() -> None:
    assert (
        MassiveProvider(None)
        .fetch_daily_bars(QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 2))
        .status
        == "NOT_CONFIGURED"
    )

    def transport(*_args: object) -> tuple[int, object]:
        return 200, {
            "status": "OK",
            "results": [{"t": 1_704_171_600_000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9}],
        }

    result = MassiveProvider("local-test-key", transport=transport).fetch_daily_bars(
        QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 5)
    )
    assert result.adjustment_mode == "splits"
    assert result.bars[0].adjusted_close is None
    assert result.bars[0].close == 1.5


def test_alpha_vantage_does_not_request_the_premium_adjusted_function() -> None:
    seen: dict[str, str] = {}

    def transport(_url: str, params: dict[str, str], _timeout: float) -> tuple[int, object]:
        seen.update(params)
        return 200, {
            "Time Series (Daily)": {
                "2024-01-03": {
                    "1. open": "1",
                    "2. high": "2",
                    "3. low": "1",
                    "4. close": "1.5",
                    "5. volume": "3",
                },
                "2024-01-02": {
                    "1. open": "1",
                    "2. high": "2",
                    "3. low": "1",
                    "4. close": "1.2",
                    "5. volume": "3",
                },
            }
        }

    result = AlphaVantageProvider("local-test-key", transport=transport).fetch_daily_bars(
        QQQ_INSTRUMENT, date(2024, 1, 2), date(2024, 1, 3)
    )
    assert seen["function"] == "TIME_SERIES_DAILY"
    assert result.adjustment_mode == "none"
    assert [bar.trading_date.isoformat() for bar in result.bars] == ["2024-01-02", "2024-01-03"]


def test_yahoo_duplicate_dates_and_separate_adjusted_close() -> None:
    stamp = int(datetime(2024, 1, 2, tzinfo=UTC).timestamp())

    def transport(*_args: object) -> tuple[int, object]:
        return 200, {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD", "exchangeName": "NGM"},
                        "timestamp": [stamp, stamp],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10, 10],
                                    "high": [12, 12],
                                    "low": [9, 9],
                                    "close": [11, 11],
                                    "volume": [100, 100],
                                }
                            ],
                            "adjclose": [{"adjclose": [8, 8]}],
                        },
                    }
                ],
                "error": None,
            }
        }

    result = YahooFinanceProvider(transport=transport).fetch_daily_bars(
        QQQ_INSTRUMENT, date(2024, 1, 1), date(2024, 1, 5)
    )
    assert result.provider == "yahoo"
    assert len(result.bars) == 1
    assert result.bars[0].close == 11
    assert result.bars[0].adjusted_close == 8


def test_comparison_reports_gaps_and_uses_adjusted_close_when_present() -> None:
    left = pl.DataFrame(
        {
            "trading_date": [date(2024, 1, 2), date(2024, 1, 3)],
            "close": [100.0, 110.0],
            "adjusted_close": [None, None],
            "volume": [10.0, 10.0],
            "adjustment_mode": ["all", "all"],
        }
    )
    right = pl.DataFrame(
        {
            "trading_date": [date(2024, 1, 2), date(2024, 1, 4)],
            "close": [200.0, 50.0],
            "adjusted_close": [101.0, 50.0],
            "volume": [12.0, 1.0],
            "adjustment_mode": ["raw_and_split_dividend", "raw_and_split_dividend"],
        }
    )
    priced = left.with_columns(continuity_close(left).alias("used"))
    assert priced.get_column("used").to_list() == [100.0, 110.0]
    report = compare_sessions(left, right, left_name="twelvedata", right_name="tiingo")
    assert report["common_sessions"] == 1
    assert report["missing_on_right"] == 1
    assert report["missing_on_left"] == 1
    close = report["close"]
    assert isinstance(close, dict)
    assert close["max_absolute_difference"] == 1.0


def test_second_store_does_not_replace_the_training_file(settings: AppSettings) -> None:
    training = MarketStore(settings)
    other = MarketStore(settings, provider="yahoo", adjustment_mode="raw_ohlc_plus_adjclose")
    assert training.path.name == "twelvedata_all.parquet"
    assert other.path != training.path


def test_missing_market_key_status_does_not_require_a_widget(settings: AppSettings) -> None:
    tuned = settings.model_copy(update={"twelve_data_api_key": None, "offline_mode": False})
    status = build_application_status(tuned, sec_status="No data")
    assert status.market_health == "NOT_CONFIGURED"
    assert status.market_provider == "twelvedata"
    assert health_from_status("rate_limit") == "RATE_LIMITED"
