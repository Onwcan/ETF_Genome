"""Opt-in Twelve Data check. Normal pytest does not run this test."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.market_sync import completed_session_end
from etf_genome.data.sources.market import QQQ_INSTRUMENT
from etf_genome.data.sources.twelve_data import TwelveDataProvider


@pytest.mark.skipif(
    os.environ.get("ETF_GENOME_RUN_LIVE_MARKET_TESTS") != "1",
    reason="Set ETF_GENOME_RUN_LIVE_MARKET_TESTS=1 to contact Twelve Data",
)
def test_live_qqq_daily_bars_parse() -> None:
    settings = AppSettings()
    if settings.twelve_data_key_value() is None:
        pytest.fail("ETF_GENOME_TWELVE_DATA_API_KEY is not configured")
    end = completed_session_end(datetime.now(UTC))
    start = end - timedelta(days=10)
    result = TwelveDataProvider(
        settings.twelve_data_key_value(),
        timeout=settings.network_timeout_seconds,
    ).fetch_daily_bars(QQQ_INSTRUMENT, start, end)
    assert result.status == "ok"
    assert result.adjustment_mode == "all"
    assert result.bars
    assert result.bars[-1].close is not None
    assert result.bars[-1].adjusted_close is None
