"""Freshness and backoff tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from etf_genome.config.settings import AppSettings
from etf_genome.sync.status import Freshness, backoff_delay_seconds, classify_freshness

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def test_current_requires_a_recent_successful_check_not_a_recent_download() -> None:
    status = classify_freshness(
        now=NOW,
        last_checked_at=NOW - timedelta(hours=2),
        last_error_class=None,
        has_data=True,
        stale_after=timedelta(hours=12),
        in_progress=False,
    )
    assert status is Freshness.CURRENT


def test_old_check_is_stale_even_when_holdings_exist() -> None:
    status = classify_freshness(
        now=NOW,
        last_checked_at=NOW - timedelta(days=3),
        last_error_class=None,
        has_data=True,
        stale_after=timedelta(hours=12),
        in_progress=False,
    )
    assert status is Freshness.STALE


def test_offline_and_empty_states() -> None:
    offline = classify_freshness(
        now=NOW,
        last_checked_at=NOW,
        last_error_class="offline",
        has_data=True,
        stale_after=timedelta(hours=12),
        in_progress=False,
    )
    empty = classify_freshness(
        now=NOW,
        last_checked_at=None,
        last_error_class=None,
        has_data=False,
        stale_after=timedelta(hours=12),
        in_progress=False,
    )
    checking = classify_freshness(
        now=NOW,
        last_checked_at=None,
        last_error_class=None,
        has_data=False,
        stale_after=timedelta(hours=12),
        in_progress=True,
    )
    assert offline is Freshness.OFFLINE
    assert empty is Freshness.NO_DATA
    assert checking is Freshness.CHECKING


def test_backoff_grows_and_is_capped() -> None:
    assert backoff_delay_seconds(1) == 15 * 60
    assert backoff_delay_seconds(2) == 30 * 60
    assert backoff_delay_seconds(12) == 6 * 60 * 60


def test_request_rate_cannot_reach_ten_per_second() -> None:
    with pytest.raises(ValidationError):
        AppSettings(sec_requests_per_second=10)
    settings = AppSettings(sec_requests_per_second=2, sec_min_interval_seconds=0)
    assert settings.sec_sync_interval_seconds == pytest.approx(0.5)


def test_refresh_interval_cannot_be_shorter_than_an_hour() -> None:
    with pytest.raises(ValidationError):
        AppSettings(sec_update_interval_hours=0.01)
