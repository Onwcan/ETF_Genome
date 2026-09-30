"""Background synchronization policy for local provider updates."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.market_sync import MarketSyncResult, sync_qqq_market
from etf_genome.data.ingestion.sec_nport import (
    FilingValidationError,
    IngestWorkResult,
    SecNportSync,
)
from etf_genome.data.storage.sync_repository import SyncRepository, SyncStateRecord, parse_timestamp
from etf_genome.domain.funds import QQQ
from etf_genome.errors import EtfGenomeError
from etf_genome.sync.status import Freshness, backoff_delay_seconds, classify_freshness

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncOutcome:
    """User-facing result of one synchronization request."""

    status: str
    changed: bool
    message: str
    filings_discovered: int = 0
    filings_ingested: int = 0
    filings_skipped: int = 0
    report_dates: tuple[str, ...] = ()
    accessions: tuple[str, ...] = ()
    already_running: bool = False
    error_class: str | None = None
    market_status: str = ""
    market_message: str = ""
    market_latest: str | None = None
    risk_text: str = ""


class UpdateCoordinator:
    """Run provider sync outside the UI and keep a single flight per call."""

    def __init__(
        self,
        settings: AppSettings,
        repository: SyncRepository,
        sec_sync: SecNportSync,
        *,
        clock: Callable[[], datetime] | None = None,
        classify_error: Callable[[Exception], str] | None = None,
        market_sync: Callable[..., MarketSyncResult] | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._sec_sync = sec_sync
        self._clock = clock or (lambda: datetime.now(UTC))
        self._classify_error = classify_error or classify_sync_error
        self._market_sync = market_sync or sync_qqq_market
        self._lock = threading.Lock()
        self._market_lock = threading.Lock()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def close(self) -> None:
        self._sec_sync.close()

    def sync_sec(self, reason: str) -> SyncOutcome:
        """Synchronize QQQ N-PORT filings.

        ``startup`` and ``periodic`` respect the refresh interval and backoff.
        ``manual`` still refuses to overlap another run or to ignore backoff
        after a provider failure.
        """

        if not self._lock.acquire(blocking=False):
            return SyncOutcome(
                status=Freshness.CHECKING.value,
                changed=False,
                message="A synchronization is already running.",
                already_running=True,
            )
        try:
            self._cancel.clear()
            return self._sync_locked(reason)
        finally:
            self._lock.release()

    def sync_market(self, reason: str) -> MarketSyncResult:
        """Refresh completed QQQ daily bars on the market-data interval."""

        if not self._market_lock.acquire(blocking=False):
            return MarketSyncResult(
                status="checking",
                message="A market synchronization is already running.",
                symbol="QQQ",
                provider="twelvedata",
                adjustment_mode="all",
                requested_start=None,
                requested_end=None,
                received_bars=0,
                existing_bars=0,
                new_bars=0,
                latest_trading_date=None,
                storage_path="",
            )
        try:
            return self._sync_market_locked(reason)
        finally:
            self._market_lock.release()

    def sync_background(self, reason: str) -> SyncOutcome:
        """Check SEC filings and daily prices, then score the cached risk models."""

        outcome = self.sync_sec(reason)
        market = self.sync_market(reason)
        message = outcome.message
        if market.message:
            message = f"{outcome.message} {market.message}"
        return replace(
            outcome,
            message=message,
            market_status=market.status,
            market_message=market.message,
            market_latest=market.latest_trading_date,
            risk_text=_risk_text(self._settings),
        )

    def _sync_market_locked(self, reason: str) -> MarketSyncResult:
        now = self._clock()
        state = self._repository.get_sync_state("twelvedata", "ticker:QQQ")
        if self._settings.offline_mode:
            return MarketSyncResult(
                status="offline",
                message="Offline mode is on. Showing locally cached market data.",
                symbol="QQQ",
                provider="twelvedata",
                adjustment_mode="all",
                requested_start=None,
                requested_end=None,
                received_bars=0,
                existing_bars=0,
                new_bars=0,
                latest_trading_date=None if state is None else state.last_ingested_item,
                storage_path="",
            )
        if reason != "manual" and _market_interval(state, now, self._settings):
            return MarketSyncResult(
                status="current",
                message="Market prices were checked recently. No new request was sent.",
                symbol="QQQ",
                provider="twelvedata",
                adjustment_mode="all",
                requested_start=None,
                requested_end=None,
                received_bars=0,
                existing_bars=0,
                new_bars=0,
                latest_trading_date=None if state is None else state.last_ingested_item,
                storage_path="",
            )
        if state is not None and state.next_allowed_attempt is not None:
            allowed = parse_timestamp(state.next_allowed_attempt)
            if allowed is not None and now < allowed:
                return MarketSyncResult(
                    status="error",
                    message=f"Market synchronization is waiting until {allowed.isoformat()}.",
                    symbol="QQQ",
                    provider="twelvedata",
                    adjustment_mode="all",
                    requested_start=None,
                    requested_end=None,
                    received_bars=0,
                    existing_bars=0,
                    new_bars=0,
                    latest_trading_date=None if state is None else state.last_ingested_item,
                    storage_path="",
                )
        result = self._market_sync(self._settings, now=now)
        if result.status in {"ok", "current"}:
            self._repository.save_sync_state(
                SyncStateRecord(
                    provider="twelvedata",
                    entity_id="ticker:QQQ",
                    last_attempt_at=now.isoformat(),
                    last_success_at=now.isoformat(),
                    last_seen_remote_item=result.latest_trading_date,
                    last_ingested_item=result.latest_trading_date,
                    consecutive_failures=0,
                    next_allowed_attempt=None,
                    last_error=None,
                    last_error_class=None,
                )
            )
            return result
        if result.status == "NOT_CONFIGURED":
            self._repository.save_sync_state(
                SyncStateRecord(
                    provider="twelvedata",
                    entity_id="ticker:QQQ",
                    last_attempt_at=now.isoformat(),
                    last_success_at=None if state is None else state.last_success_at,
                    last_seen_remote_item=None if state is None else state.last_seen_remote_item,
                    last_ingested_item=None if state is None else state.last_ingested_item,
                    consecutive_failures=0,
                    next_allowed_attempt=None,
                    last_error="NOT_CONFIGURED",
                    last_error_class="config",
                )
            )
            return result
        failures = 1 if state is None else state.consecutive_failures + 1
        delay = backoff_delay_seconds(failures)
        self._repository.save_sync_state(
            SyncStateRecord(
                provider="twelvedata",
                entity_id="ticker:QQQ",
                last_attempt_at=now.isoformat(),
                last_success_at=None if state is None else state.last_success_at,
                last_seen_remote_item=None if state is None else state.last_seen_remote_item,
                last_ingested_item=None if state is None else state.last_ingested_item,
                consecutive_failures=failures,
                next_allowed_attempt=(now + timedelta(seconds=delay)).isoformat(),
                last_error=result.status,
                last_error_class=result.status,
            )
        )
        return result

    def _sync_locked(self, reason: str) -> SyncOutcome:
        now = self._clock()
        state = self._repository.get_sync_state("sec", QQQ.fund_id)
        if self._settings.offline_mode:
            return self._offline_outcome(state)
        if not self._settings.sec_user_agent_is_configured():
            return SyncOutcome(
                status=Freshness.ERROR.value,
                changed=False,
                message=(
                    "SEC live synchronization is off until ETF_GENOME_SEC_USER_AGENT "
                    "contains an application name and a contact email. "
                    "ETF Genome does not send a placeholder address."
                ),
                error_class="config",
            )
        if reason != "manual" and _within_interval(state, now, self._settings):
            return SyncOutcome(
                status=Freshness.CURRENT.value,
                changed=False,
                message="SEC filings were checked recently. No new request was sent.",
            )
        if state is not None and state.next_allowed_attempt is not None:
            allowed = parse_timestamp(state.next_allowed_attempt)
            if allowed is not None and now < allowed:
                return SyncOutcome(
                    status=Freshness.ERROR.value,
                    changed=False,
                    message=f"SEC synchronization is waiting until {allowed.isoformat()}.",
                    error_class=state.last_error_class,
                )
        self._mark_attempt(state, now)
        try:
            result = self._sec_sync.run(cancelled=self._cancel.is_set)
        except EtfGenomeError as exc:
            return self._fail(state, now, exc)
        self._mark_success(state, now, result)
        status = Freshness.CURRENT.value
        if result.changed:
            message = (
                f"Stored {len(result.ingested)} new NPORT-P filing"
                f"{'' if len(result.ingested) == 1 else 's'}."
            )
        else:
            message = "No new NPORT-P filings. Local holdings were left unchanged."
        logger.info(
            "SEC synchronization finished",
            extra={
                "provider": "sec",
                "fund_id": QQQ.fund_id,
                "operation": reason,
                "result": "changed" if result.changed else "unchanged",
            },
        )
        return SyncOutcome(
            status=status,
            changed=result.changed,
            message=message,
            filings_discovered=result.discovered,
            filings_ingested=len(result.ingested),
            filings_skipped=len(result.skipped),
            report_dates=result.report_dates,
            accessions=result.ingested + result.skipped,
        )

    def _offline_outcome(self, state: SyncStateRecord | None) -> SyncOutcome:
        status = classify_freshness(
            now=self._clock(),
            last_checked_at=parse_timestamp(None if state is None else state.last_success_at),
            last_error_class="offline",
            has_data=state is not None and state.last_ingested_item is not None,
            stale_after=timedelta(hours=self._settings.stale_after_hours),
            in_progress=False,
        )
        return SyncOutcome(
            status=status.value,
            changed=False,
            message="Offline mode is on. Showing locally cached holdings.",
            error_class="offline",
        )

    def _mark_attempt(self, state: SyncStateRecord | None, now: datetime) -> None:
        self._repository.save_sync_state(
            SyncStateRecord(
                provider="sec",
                entity_id=QQQ.fund_id,
                last_attempt_at=now.isoformat(),
                last_success_at=None if state is None else state.last_success_at,
                last_seen_remote_item=None if state is None else state.last_seen_remote_item,
                last_ingested_item=None if state is None else state.last_ingested_item,
                consecutive_failures=0 if state is None else state.consecutive_failures,
                next_allowed_attempt=None if state is None else state.next_allowed_attempt,
                last_error=None if state is None else state.last_error,
                last_error_class=None if state is None else state.last_error_class,
            )
        )

    def _mark_success(
        self,
        state: SyncStateRecord | None,
        now: datetime,
        result: IngestWorkResult,
    ) -> None:
        newest = result.seen[0] if result.seen else None
        ingested = (
            result.ingested[-1]
            if result.ingested
            else (None if state is None else state.last_ingested_item)
        )
        self._repository.save_sync_state(
            SyncStateRecord(
                provider="sec",
                entity_id=QQQ.fund_id,
                last_attempt_at=now.isoformat(),
                last_success_at=now.isoformat(),
                last_seen_remote_item=newest,
                last_ingested_item=ingested,
                consecutive_failures=0,
                next_allowed_attempt=None,
                last_error=None,
                last_error_class=None,
            )
        )
        self._repository.save_freshness(
            provider="sec",
            resource_type="nport-p",
            resource_id=QQQ.fund_id,
            source_as_of=result.report_dates[0] if result.report_dates else None,
            source_published_at=None,
            downloaded_at=now.isoformat() if result.changed else None,
            last_checked_at=now.isoformat(),
            last_successful_sync_at=now.isoformat(),
            content_hash=None,
            status=Freshness.CURRENT.value,
            error_message=None,
        )

    def _fail(
        self, state: SyncStateRecord | None, now: datetime, exc: EtfGenomeError
    ) -> SyncOutcome:
        kind = self._classify_error(exc)
        failures = 1 if state is None else state.consecutive_failures + 1
        delay = backoff_delay_seconds(failures)
        next_allowed = now + timedelta(seconds=delay)
        logger.warning(
            "SEC synchronization failed",
            extra={
                "provider": "sec",
                "fund_id": QQQ.fund_id,
                "operation": "sync",
                "result": kind,
            },
        )
        self._repository.save_sync_state(
            SyncStateRecord(
                provider="sec",
                entity_id=QQQ.fund_id,
                last_attempt_at=now.isoformat(),
                last_success_at=None if state is None else state.last_success_at,
                last_seen_remote_item=None if state is None else state.last_seen_remote_item,
                last_ingested_item=None if state is None else state.last_ingested_item,
                consecutive_failures=failures,
                next_allowed_attempt=next_allowed.isoformat(),
                last_error=type(exc).__name__,
                last_error_class=kind,
            )
        )
        has_data = state is not None and state.last_ingested_item is not None
        status = classify_freshness(
            now=now,
            last_checked_at=now,
            last_error_class=kind,
            has_data=has_data,
            stale_after=timedelta(hours=self._settings.stale_after_hours),
            in_progress=False,
        )
        return SyncOutcome(
            status=status.value,
            changed=False,
            message=public_sync_message(kind),
            error_class=kind,
        )


def classify_sync_error(exc: Exception) -> str:
    """Map an SEC or parser failure onto a small set of user-facing classes."""

    from etf_genome.data.sources.sec.errors import (
        SecConfigError,
        SecHttpError,
        SecRetryExhausted,
        SecTimeoutError,
        SecTransportError,
    )
    from etf_genome.data.sources.sec.nport_xml import NportXmlError

    if isinstance(exc, SecConfigError):
        return "config"
    if isinstance(exc, SecTimeoutError):
        return "timeout"
    if isinstance(exc, NportXmlError):
        return "parse"
    if isinstance(exc, FilingValidationError):
        return "validation"
    if isinstance(exc, SecHttpError):
        if exc.status_code == 403:
            return "rejected"
        if exc.status_code == 429:
            return "rate_limit"
        if exc.status_code >= 500:
            return "server"
        return "rejected"
    if isinstance(exc, SecRetryExhausted):
        cause = exc.__cause__
        if isinstance(cause, SecHttpError) and cause.status_code == 429:
            return "rate_limit"
        if isinstance(cause, SecTimeoutError):
            return "timeout"
        return "server"
    if isinstance(exc, SecTransportError):
        return "offline" if exc.kind == "offline" else "server"
    return "server"


def public_sync_message(kind: str) -> str:
    """Return a message safe to show in the desktop window."""

    messages = {
        "offline": "SEC synchronization unavailable. Showing locally cached holdings.",
        "timeout": "SEC synchronization timed out. Showing locally cached holdings.",
        "rejected": "SEC rejected the request. Check the declared User-Agent contact.",
        "rate_limit": "SEC rate limit reached. ETF Genome will wait before trying again.",
        "server": "SEC returned a server error. Showing locally cached holdings.",
        "parse": "The SEC filing could not be parsed. Previous holdings were kept.",
        "validation": "The SEC filing did not match this fund. Previous holdings were kept.",
        "config": "SEC synchronization is not configured.",
    }
    return messages.get(kind, "SEC synchronization failed. Showing locally cached holdings.")


def _risk_text(settings: AppSettings) -> str:
    try:
        from etf_genome.services.risk_inference import estimate_qqq_risk, format_risk_estimate

        return format_risk_estimate(estimate_qqq_risk(settings))
    except Exception:
        logger.exception("Risk inference failed")
        return "Risk Baseline\nMarket data unavailable."


def _market_interval(state: SyncStateRecord | None, now: datetime, settings: AppSettings) -> bool:
    if state is None or state.last_success_at is None or state.last_error_class is not None:
        return False
    success = parse_timestamp(state.last_success_at)
    if success is None:
        return False
    return now - success <= timedelta(hours=settings.market_update_interval_hours)


def _within_interval(state: SyncStateRecord | None, now: datetime, settings: AppSettings) -> bool:
    if state is None or state.last_success_at is None or state.last_error_class is not None:
        return False
    success = parse_timestamp(state.last_success_at)
    if success is None:
        return False
    return now - success <= timedelta(hours=settings.sec_update_interval_hours)
