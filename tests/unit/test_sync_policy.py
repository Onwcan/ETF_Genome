"""Synchronization policy tests. No network."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.market_sync import MarketSyncResult
from etf_genome.data.ingestion.sec_nport import IngestWorkResult
from etf_genome.data.sources.sec.errors import SecTransportError
from etf_genome.data.storage.sqlite_catalog import SqliteCatalog
from etf_genome.data.storage.sync_repository import SyncRepository, SyncStateRecord
from etf_genome.domain.funds import QQQ
from etf_genome.sync.coordinator import UpdateCoordinator
from etf_genome.sync.status import Freshness

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


class FakeSecSync:
    def __init__(
        self, result: IngestWorkResult | None = None, error: Exception | None = None
    ) -> None:
        self.calls = 0
        self.result = result or IngestWorkResult(
            discovered=1,
            ingested=("0001067839-25-000090",),
            skipped=(),
            seen=("0001067839-25-000090",),
            report_dates=("2025-06-30",),
            changed=True,
        )
        self.error = error
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False

    def run(self, *, cancelled):
        self.calls += 1
        self.started.set()
        if self.block:
            self.release.wait(2)
        if self.error is not None:
            raise self.error
        return self.result


def _coordinator(settings: AppSettings, fake: FakeSecSync) -> UpdateCoordinator:
    tuned = settings.model_copy(
        update={"sec_user_agent": "ETF Genome Tests tester@example.com", "offline_mode": False}
    )
    repository = SyncRepository(SqliteCatalog(tuned.sqlite_path))
    return UpdateCoordinator(tuned, repository, fake, clock=lambda: NOW)  # type: ignore[arg-type]


def test_recent_success_does_not_sync_again(settings: AppSettings) -> None:
    fake = FakeSecSync()
    coordinator = _coordinator(settings, fake)
    repository = SyncRepository(SqliteCatalog(settings.sqlite_path))
    repository.save_sync_state(
        SyncStateRecord(
            provider="sec",
            entity_id=QQQ.fund_id,
            last_attempt_at=NOW.isoformat(),
            last_success_at=NOW.isoformat(),
            last_seen_remote_item="0001067839-25-000090",
            last_ingested_item="0001067839-25-000090",
            consecutive_failures=0,
            next_allowed_attempt=None,
            last_error=None,
            last_error_class=None,
        )
    )
    outcome = coordinator.sync_sec("startup")
    assert outcome.status == Freshness.CURRENT.value
    assert fake.calls == 0
    assert outcome.changed is False


def test_offline_mode_does_not_call_the_provider(settings: AppSettings) -> None:
    fake = FakeSecSync()
    coordinator = _coordinator(settings, fake)
    coordinator._settings = settings.model_copy(update={"offline_mode": True})
    outcome = coordinator.sync_sec("startup")
    assert outcome.error_class == "offline"
    assert fake.calls == 0


def test_missing_contact_does_not_call_the_provider(settings: AppSettings) -> None:
    fake = FakeSecSync()
    coordinator = _coordinator(settings, fake)
    coordinator._settings = settings.model_copy(
        update={"sec_user_agent": "ETF Genome Phase1 (research; set ETF_GENOME_SEC_USER_AGENT)"}
    )
    outcome = coordinator.sync_sec("manual")
    assert outcome.error_class == "config"
    assert "contact email" in outcome.message
    assert fake.calls == 0


def test_failure_sets_backoff_and_a_retry_does_not_hammer(settings: AppSettings) -> None:
    fake = FakeSecSync(error=SecTransportError("dns failed", kind="offline"))
    coordinator = _coordinator(settings, fake)
    first = coordinator.sync_sec("manual")
    second = coordinator.sync_sec("manual")
    assert first.error_class == "offline"
    assert first.message.startswith("SEC synchronization unavailable")
    assert fake.calls == 1
    assert "waiting" in second.message
    state = SyncRepository(SqliteCatalog(settings.sqlite_path)).get_sync_state("sec", QQQ.fund_id)
    assert state is not None
    assert state.consecutive_failures == 1
    assert state.next_allowed_attempt is not None


def test_only_one_sync_runs_at_a_time(settings: AppSettings) -> None:
    fake = FakeSecSync()
    fake.block = True
    coordinator = _coordinator(settings, fake)
    worker = threading.Thread(target=coordinator.sync_sec, args=("manual",))
    worker.start()
    assert fake.started.wait(2)
    overlapping = coordinator.sync_sec("manual")
    fake.release.set()
    worker.join(3)
    assert overlapping.already_running is True
    assert fake.calls == 1


def test_success_resets_backoff(settings: AppSettings) -> None:
    fake = FakeSecSync()
    coordinator = _coordinator(settings, fake)
    repository = SyncRepository(SqliteCatalog(settings.sqlite_path))
    repository.save_sync_state(
        SyncStateRecord(
            provider="sec",
            entity_id=QQQ.fund_id,
            last_attempt_at=(NOW - timedelta(hours=1)).isoformat(),
            last_success_at=None,
            last_seen_remote_item=None,
            last_ingested_item=None,
            consecutive_failures=3,
            next_allowed_attempt=(NOW - timedelta(seconds=1)).isoformat(),
            last_error="SecTimeoutError",
            last_error_class="timeout",
        )
    )
    outcome = coordinator.sync_sec("manual")
    state = repository.get_sync_state("sec", QQQ.fund_id)
    assert outcome.changed is True
    assert state is not None
    assert state.consecutive_failures == 0
    assert state.next_allowed_attempt is None
    assert state.last_error_class is None


class MarketCalls:
    def __init__(self, status: str = "ok") -> None:
        self.calls = 0
        self.status = status

    def __call__(
        self, settings: AppSettings, provider: object = None, *, now: object = None
    ) -> MarketSyncResult:
        self.calls += 1
        return MarketSyncResult(
            status=self.status,
            message=self.status,
            symbol="QQQ",
            provider="twelvedata",
            adjustment_mode="all",
            requested_start="2024-01-01",
            requested_end="2024-01-02",
            received_bars=0,
            existing_bars=1,
            new_bars=0,
            latest_trading_date="2024-01-02",
            storage_path="twelvedata_all.parquet",
        )


def test_market_refresh_uses_its_own_interval(settings: AppSettings) -> None:
    fake = FakeSecSync()
    market = MarketCalls()
    coordinator = UpdateCoordinator(
        settings.model_copy(update={"offline_mode": False}),
        SyncRepository(SqliteCatalog(settings.sqlite_path)),
        fake,  # type: ignore[arg-type]
        clock=lambda: NOW,
        market_sync=market,
    )
    repository = SyncRepository(SqliteCatalog(settings.sqlite_path))
    repository.save_sync_state(
        SyncStateRecord(
            provider="twelvedata",
            entity_id="ticker:QQQ",
            last_attempt_at=NOW.isoformat(),
            last_success_at=(NOW - timedelta(hours=2)).isoformat(),
            last_seen_remote_item="2024-01-02",
            last_ingested_item="2024-01-02",
            consecutive_failures=0,
            next_allowed_attempt=None,
            last_error=None,
            last_error_class=None,
        )
    )
    skipped = coordinator.sync_market("startup")
    assert skipped.status == "current"
    assert market.calls == 0
    coordinator.sync_market("manual")
    assert market.calls == 1


def test_market_rate_limit_backs_off_without_a_second_call(settings: AppSettings) -> None:
    market = MarketCalls("rate_limit")
    coordinator = UpdateCoordinator(
        settings,
        SyncRepository(SqliteCatalog(settings.sqlite_path)),
        FakeSecSync(),  # type: ignore[arg-type]
        clock=lambda: NOW,
        market_sync=market,
    )
    first = coordinator.sync_market("manual")
    second = coordinator.sync_market("manual")
    assert first.status == "rate_limit"
    assert market.calls == 1
    assert "waiting" in second.message


def test_missing_market_key_is_not_configured(settings: AppSettings) -> None:
    coordinator = UpdateCoordinator(
        settings.model_copy(update={"twelve_data_api_key": None, "offline_mode": False}),
        SyncRepository(SqliteCatalog(settings.sqlite_path)),
        FakeSecSync(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    result = coordinator.sync_market("manual")
    assert result.status == "NOT_CONFIGURED"
