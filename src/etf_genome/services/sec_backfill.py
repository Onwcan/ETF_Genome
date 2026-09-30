"""One-fund historical NPORT-P backfill. The desktop sync cap stays at two."""

from __future__ import annotations

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.sec_nport import SecNportSync
from etf_genome.data.sources.sec.client import SecClient
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.domain.funds import QQQ


def backfill_qqq_filings(settings: AppSettings, *, max_filings: int = 40) -> dict[str, object]:
    """Ingest discovered QQQ NPORT-P filings that are not already stored."""

    tuned = settings.model_copy(
        update={
            "sec_timeout_seconds": settings.network_timeout_seconds,
            "sec_min_interval_seconds": settings.sec_sync_interval_seconds,
        }
    )
    store = LocalHoldingsStore(tuned)
    repository = SyncRepository(store.catalog)
    client = SecClient(tuned)
    sync = SecNportSync(tuned, client, store, repository)
    try:
        result = sync.run(max_filings=max_filings, continue_on_error=True)
    finally:
        sync.close()
    filings = repository.list_filings(QQQ.fund_id)
    report_dates = sorted(item.report_date for item in filings if item.report_date)
    published = sorted(str(item.filed_at)[:10] for item in filings if item.filed_at)
    return {
        "discovered": result.discovered,
        "already_stored": len(result.skipped),
        "newly_downloaded": len(result.ingested),
        "successfully_parsed": len(result.ingested),
        "failed": list(result.failed),
        "filings_stored": len(filings),
        "report_date_min": report_dates[0] if report_dates else None,
        "report_date_max": report_dates[-1] if report_dates else None,
        "publication_date_min": published[0] if published else None,
        "publication_date_max": published[-1] if published else None,
    }
