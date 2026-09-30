"""Local view of the tracked fund. This module does not call the network."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from etf_genome.config.settings import AppSettings
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository, parse_timestamp
from etf_genome.domain.funds import QQQ, TrackedFund
from etf_genome.drift import compute_drift
from etf_genome.genome import build_genome_report
from etf_genome.sync.status import classify_freshness


@dataclass(frozen=True)
class FundView:
    """Cached analytics plus freshness labels for one fund."""

    fund_name: str
    ticker: str
    data_source: str
    holdings_as_of: date | None
    published_at: str | None
    downloaded_at: str | None
    last_checked_at: str | None
    freshness: str
    status_message: str
    holdings_count: int | None
    top_10_weight: float | None
    hhi: float | None
    drift_value: float | None
    drift_metric: str
    from_date: date | None
    to_date: date | None


def build_fund_view(
    settings: AppSettings,
    fund: TrackedFund = QQQ,
    *,
    in_progress: bool = False,
) -> FundView:
    """Read Parquet and SQLite and calculate metrics only from stored snapshots."""

    settings.ensure_directories()
    store = LocalHoldingsStore(settings)
    repository = SyncRepository(store.catalog)
    dates = store.catalog.list_snapshot_dates(fund.fund_id)
    filings = repository.list_filings(fund.fund_id)
    state = repository.get_sync_state("sec", fund.fund_id)
    latest_filing = filings[-1] if filings else None
    last_checked = None if state is None else (state.last_attempt_at or state.last_success_at)
    if settings.offline_mode:
        freshness_value = "OFFLINE"
    else:
        freshness_value = classify_freshness(
            now=datetime.now(UTC),
            last_checked_at=parse_timestamp(None if state is None else state.last_success_at),
            last_error_class=None if state is None else state.last_error_class,
            has_data=bool(dates),
            stale_after=timedelta(hours=settings.stale_after_hours),
            in_progress=in_progress,
        ).value
    if not dates:
        return FundView(
            fund_name=fund.name,
            ticker=fund.ticker,
            data_source="SEC N-PORT",
            holdings_as_of=None,
            published_at=None,
            downloaded_at=None,
            last_checked_at=last_checked,
            freshness=freshness_value,
            status_message=_status_message(_empty_message(settings), settings, has_data=False),
            holdings_count=None,
            top_10_weight=None,
            hhi=None,
            drift_value=None,
            drift_metric="jensen_shannon_distance",
            from_date=None,
            to_date=None,
        )
    later = store.read_holdings(fund.fund_id, dates[-1])
    report = build_genome_report(later)
    drift_value = None
    drift_metric = "jensen_shannon_distance"
    from_date = None
    message = ""
    if len(dates) >= 2:
        earlier = store.read_holdings(fund.fund_id, dates[-2])
        drift = compute_drift(earlier, later)
        drift_value = drift.overall_drift
        drift_metric = drift.overall_drift_metric
        from_date = dates[-2]
        if drift.sector_drift.metric == "unavailable":
            message = (
                "Sector drift is unavailable because N-PORT does not provide "
                "sector classifications."
            )
    return FundView(
        fund_name=report.fund_name or fund.name,
        ticker=report.ticker or fund.ticker,
        data_source="SEC N-PORT",
        holdings_as_of=dates[-1],
        published_at=None if latest_filing is None else latest_filing.filed_at,
        downloaded_at=None if latest_filing is None else latest_filing.downloaded_at,
        last_checked_at=last_checked,
        freshness=freshness_value,
        status_message=_status_message(message, settings, has_data=True),
        holdings_count=report.concentration.holdings_count,
        top_10_weight=report.concentration.top_10_weight,
        hhi=report.concentration.hhi,
        drift_value=drift_value,
        drift_metric=drift_metric,
        from_date=from_date,
        to_date=dates[-1],
    )


def _status_message(message: str, settings: AppSettings, *, has_data: bool) -> str:
    if settings.offline_mode and has_data:
        prefix = "Offline mode is on. Cached holdings remain available."
        return f"{prefix} {message}".strip()
    return message


def _empty_message(settings: AppSettings) -> str:
    if not settings.sec_user_agent_is_configured():
        return (
            "No local N-PORT holdings yet. Set ETF_GENOME_SEC_USER_AGENT to an "
            "application name and contact email before SEC synchronization can run."
        )
    if settings.offline_mode:
        return "Offline mode is on and no local N-PORT holdings are stored."
    return "No local N-PORT holdings yet."
