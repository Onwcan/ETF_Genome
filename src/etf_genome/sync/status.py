"""Freshness labels for locally cached provider data."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum


class Freshness(StrEnum):
    """Whether the local copy has been checked under the provider policy."""

    CURRENT = "CURRENT"
    STALE = "STALE"
    CHECKING = "CHECKING"
    UPDATING = "UPDATING"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    NO_DATA = "NO_DATA"


_LABELS = {
    Freshness.CURRENT: "Up to date",
    Freshness.STALE: "Stale",
    Freshness.CHECKING: "Checking",
    Freshness.UPDATING: "Updating",
    Freshness.OFFLINE: "Offline",
    Freshness.ERROR: "Error",
    Freshness.NO_DATA: "No data",
}


def freshness_label(status: str) -> str:
    try:
        return _LABELS[Freshness(status)]
    except ValueError:
        return status


def classify_freshness(
    *,
    now: datetime,
    last_checked_at: datetime | None,
    last_error_class: str | None,
    has_data: bool,
    stale_after: timedelta,
    in_progress: bool,
) -> Freshness:
    """Classify local data without treating a recent download as proof of freshness.

    CURRENT means a successful check happened inside the provider interval and
    the last check did not fail. A quarterly holdings report can be CURRENT
    even though its portfolio date is months old.
    """

    if in_progress:
        return Freshness.CHECKING
    if last_error_class == "offline":
        return Freshness.OFFLINE
    if last_error_class:
        return Freshness.ERROR
    if not has_data:
        return Freshness.NO_DATA
    if last_checked_at is None or now - last_checked_at > stale_after:
        return Freshness.STALE
    return Freshness.CURRENT


def backoff_delay_seconds(consecutive_failures: int) -> float:
    """Return a capped delay after a failed synchronization attempt."""

    failures = max(consecutive_failures, 1)
    return float(min(6 * 60 * 60, 15 * 60 * (2 ** (failures - 1))))
