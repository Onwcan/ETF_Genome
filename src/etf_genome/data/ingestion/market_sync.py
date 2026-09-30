"""Incremental QQQ daily-bar synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.market import QQQ_INSTRUMENT, MarketBar, MarketDataProvider
from etf_genome.data.sources.twelve_data import TwelveDataProvider
from etf_genome.data.storage.market_store import MarketStore

_EASTERN = ZoneInfo("America/New_York")
_PAGE = 5000


@dataclass(frozen=True)
class MarketSyncResult:
    status: str
    message: str
    symbol: str
    provider: str
    adjustment_mode: str | None
    requested_start: str | None
    requested_end: str | None
    received_bars: int
    existing_bars: int
    new_bars: int
    latest_trading_date: str | None
    storage_path: str


def completed_session_end(now: datetime) -> date:
    """Last date whose US cash session has closed, using 16:30 America/New_York."""

    eastern = now.astimezone(_EASTERN)
    session = eastern.date()
    close = eastern.replace(hour=16, minute=30, second=0, microsecond=0)
    if eastern < close:
        session = session - timedelta(days=1)
    return session


def sync_qqq_market(
    settings: AppSettings,
    provider: MarketDataProvider | None = None,
    *,
    now: datetime | None = None,
) -> MarketSyncResult:
    """Download missing completed QQQ daily bars and upsert them."""

    store = MarketStore(settings)
    source = provider or TwelveDataProvider(
        settings.twelve_data_key_value(),
        timeout=max(settings.network_timeout_seconds, 60.0),
    )
    clock = now or datetime.now(UTC)
    latest = store.latest_date()
    start = date.fromisoformat(settings.market_history_start)
    if latest is not None:
        start = latest + timedelta(days=1)
    end = completed_session_end(clock)
    path = str(store.path.name)
    if start > end:
        return _result(
            status="current",
            message="Local market history already includes the latest completed session.",
            store=store,
            start=start,
            end=end,
            received=0,
            existing=store.read().height,
            added=0,
            path=path,
        )
    collected: list[MarketBar] = []
    cursor = start
    while cursor <= end:
        page = source.fetch_daily_bars(QQQ_INSTRUMENT, cursor, end)
        if page.status != "ok":
            if collected:
                store.upsert(collected)
            return _result(
                status=page.status,
                message=page.message,
                store=store,
                start=start,
                end=end,
                received=len(collected),
                existing=store.read().height,
                added=0,
                path=path,
                adjustment=page.adjustment_mode,
                provider_name=page.provider,
            )
        if not page.bars:
            break
        collected.extend(page.bars)
        last = page.bars[-1].trading_date
        if last >= end or len(page.bars) < _PAGE:
            break
        nxt = last + timedelta(days=1)
        if nxt <= cursor:
            break
        cursor = nxt
    existing, added = store.upsert(collected)
    adjustment = page.adjustment_mode if collected or page.adjustment_mode else "all"
    provider_name = page.provider or "twelvedata"
    return _result(
        status="ok",
        message=f"Received {len(collected)} daily bars.",
        store=store,
        start=start,
        end=end,
        received=len(collected),
        existing=existing,
        added=added,
        path=path,
        adjustment=adjustment,
        provider_name=provider_name,
    )


def _result(
    *,
    status: str,
    message: str,
    store: MarketStore,
    start: date,
    end: date,
    received: int,
    existing: int,
    added: int,
    path: str,
    adjustment: str | None = "all",
    provider_name: str = "twelvedata",
) -> MarketSyncResult:
    latest = store.latest_date()
    return MarketSyncResult(
        status=status,
        message=message,
        symbol="QQQ",
        provider=provider_name,
        adjustment_mode=adjustment,
        requested_start=start.isoformat(),
        requested_end=end.isoformat(),
        received_bars=received,
        existing_bars=existing,
        new_bars=added,
        latest_trading_date=None if latest is None else latest.isoformat(),
        storage_path=path,
    )
