"""End-to-end N-PORT ingestion against a fake SEC transport."""

from __future__ import annotations

import json
from datetime import date

import pytest
from tests.fixtures.nport_documents import EARLIER_XML, LATER_XML

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.sec_nport import SecNportSync
from etf_genome.data.sources.sec.client import SecClient
from etf_genome.data.sources.sec.discovery import filing_document_url
from etf_genome.data.sources.sec.transport import HttpResponse
from etf_genome.data.storage.http_cache import FileResponseCache
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.domain.funds import QQQ
from etf_genome.services.fund_view import build_fund_view

LATER_ACCESSION = "0001067839-25-000090"
EARLIER_ACCESSION = "0001067839-25-000080"


class MapTransport:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.urls: list[str] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> HttpResponse:
        self.urls.append(url)
        body = self.bodies.get(url)
        if body is None:
            return HttpResponse(404, b"missing")
        return HttpResponse(200, body)


def _submissions() -> bytes:
    payload = {
        "cik": "0001067839",
        "filings": {
            "recent": {
                "form": ["10-Q", "NPORT-P", "NPORT-P"],
                "accessionNumber": [
                    "0001067839-25-000001",
                    LATER_ACCESSION,
                    EARLIER_ACCESSION,
                ],
                "filingDate": ["2025-07-01", "2025-08-28", "2025-05-29"],
                "reportDate": ["2025-06-30", "2025-06-30", "2025-03-31"],
                "primaryDocument": ["cover.htm", "later.xml", "earlier.xml"],
            }
        },
    }
    return json.dumps(payload).encode("utf-8")


def _sync(settings: AppSettings, transport: MapTransport) -> SecNportSync:
    tuned = settings.model_copy(update={"sec_min_interval_seconds": 0, "sec_max_retries": 1})
    store = LocalHoldingsStore(tuned)
    client = SecClient(
        tuned,
        transport,
        FileResponseCache(tuned.cache_dir / "sec", 0),
    )
    return SecNportSync(tuned, client, store, SyncRepository(store.catalog))


def test_two_filings_ingest_once_and_calculate_drift(settings: AppSettings) -> None:
    later_url = filing_document_url(QQQ.cik, LATER_ACCESSION, "later.xml")
    earlier_url = filing_document_url(QQQ.cik, EARLIER_ACCESSION, "earlier.xml")
    submissions_url = "https://data.sec.gov/submissions/CIK0001067839.json"
    transport = MapTransport(
        {
            submissions_url: _submissions(),
            later_url: LATER_XML,
            earlier_url: EARLIER_XML,
        }
    )
    sync = _sync(settings, transport)
    first = sync.run()
    assert first.changed is True
    assert first.ingested == (LATER_ACCESSION, EARLIER_ACCESSION)
    assert len(transport.urls) == 3

    view = build_fund_view(settings)
    assert view.ticker == "QQQ"
    assert view.holdings_as_of == date(2025, 6, 30)
    assert view.published_at == "2025-08-28"
    assert view.holdings_count == 3
    assert view.top_10_weight == pytest.approx(1.0)
    assert view.hhi == pytest.approx(0.4**2 + 0.4**2 + 0.2**2)
    assert view.drift_value is not None
    assert view.drift_value > 0
    assert view.from_date == date(2025, 3, 31)
    assert "Sector drift is unavailable" in view.status_message

    stored = SyncRepository(LocalHoldingsStore(settings).catalog).get_filing(LATER_ACCESSION)
    assert stored is not None
    assert len(stored.content_hash) == 64
    before = stored.content_hash

    second = sync.run()
    assert second.changed is False
    assert second.ingested == ()
    assert second.skipped == (LATER_ACCESSION, EARLIER_ACCESSION)
    assert transport.urls[-1:] == [submissions_url]
    assert len(transport.urls) == 4
    again = SyncRepository(LocalHoldingsStore(settings).catalog).get_filing(LATER_ACCESSION)
    assert again is not None
    assert again.content_hash == before


def test_invalid_new_filing_keeps_the_previous_snapshot(settings: AppSettings) -> None:
    later_url = filing_document_url(QQQ.cik, LATER_ACCESSION, "later.xml")
    submissions_url = "https://data.sec.gov/submissions/CIK0001067839.json"
    good = {
        "cik": "0001067839",
        "filings": {
            "recent": {
                "form": ["NPORT-P"],
                "accessionNumber": [LATER_ACCESSION],
                "filingDate": ["2025-08-28"],
                "reportDate": ["2025-06-30"],
                "primaryDocument": ["later.xml"],
            }
        },
    }
    transport = MapTransport(
        {submissions_url: json.dumps(good).encode("utf-8"), later_url: LATER_XML}
    )
    sync = _sync(settings, transport)
    assert sync.run().changed is True

    bad_accession = "0001067839-25-000099"
    bad_url = filing_document_url(QQQ.cik, bad_accession, "bad.xml")
    bad = {
        "cik": "0001067839",
        "filings": {
            "recent": {
                "form": ["NPORT-P", "NPORT-P"],
                "accessionNumber": [bad_accession, LATER_ACCESSION],
                "filingDate": ["2025-09-01", "2025-08-28"],
                "reportDate": ["2025-09-30", "2025-06-30"],
                "primaryDocument": ["bad.xml", "later.xml"],
            }
        },
    }
    transport.bodies[submissions_url] = json.dumps(bad).encode("utf-8")
    transport.bodies[bad_url] = b"<not-xml"
    with pytest.raises(Exception, match="not valid XML"):
        sync.run()
    dates = LocalHoldingsStore(settings).catalog.list_snapshot_dates(QQQ.fund_id)
    assert dates == [date(2025, 6, 30)]
    assert SyncRepository(LocalHoldingsStore(settings).catalog).get_filing(bad_accession) is None
