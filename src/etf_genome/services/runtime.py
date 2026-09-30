"""Shared construction of the local SEC update coordinator."""

from __future__ import annotations

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.sec_nport import SecNportSync
from etf_genome.data.sources.sec.client import SecClient
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.sync.coordinator import UpdateCoordinator


def build_update_coordinator(settings: AppSettings) -> UpdateCoordinator:
    """Wire the SEC provider, catalog, and coordinator used by the desktop and CLI."""

    tuned = settings.model_copy(
        update={
            "sec_timeout_seconds": settings.network_timeout_seconds,
            "sec_min_interval_seconds": settings.sec_sync_interval_seconds,
        }
    )
    store = LocalHoldingsStore(tuned)
    repository = SyncRepository(store.catalog)
    client = SecClient(tuned)
    sec_sync = SecNportSync(tuned, client, store, repository)
    return UpdateCoordinator(tuned, repository, sec_sync)
