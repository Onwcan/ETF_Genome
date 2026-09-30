"""Incremental multi-ETF N-PORT ingestion using the existing SEC parser."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.sec_nport import _with_fund_context
from etf_genome.data.normalization.holdings import normalize_holdings
from etf_genome.data.sources.sec.client import SecClient
from etf_genome.data.sources.sec.discovery import (
    choose_filing_xml,
    discover_nport_filings,
    filing_document_url,
)
from etf_genome.data.sources.sec.nport_xml import PARSER_VERSION, parse_nport_xml
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.domain.funds import TrackedFund
from etf_genome.domain.models import FundMetadata
from etf_genome.graph.universe import ResolvedFund, parse_series_class_frame

CATALOGUE_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SCAN_LIMIT = 700


def download_catalogue(settings: AppSettings) -> tuple[pl.DataFrame, int]:
    """Download the official SEC fund-ticker catalogue once and cache it."""

    client = SecClient(settings)
    try:
        payload = client.get_bytes(CATALOGUE_URL, use_cache=True)
    finally:
        client.close()
    import json

    catalogue = parse_series_class_frame(json.loads(payload))
    return catalogue, len(payload)


def sync_resolved_funds(
    settings: AppSettings,
    funds: list[ResolvedFund],
    *,
    filings_per_series: int = 1,
) -> dict[str, object]:
    """Store the newest public NPORT-P filings for each resolved series.

    One submissions document is read per CIK. XML that does not match a target
    series is left cached and is not written as holdings. Existing accessions
    are not downloaded again.
    """

    targets = [fund for fund in funds if fund.status == "resolved"]
    by_cik: dict[str, list[ResolvedFund]] = defaultdict(list)
    for fund in targets:
        by_cik[fund.cik].append(fund)
    store = LocalHoldingsStore(settings)
    repository = SyncRepository(store.catalog)
    client = SecClient(settings)
    discovered = 0
    reused = 0
    downloaded = 0
    parsed = 0
    failed: list[str] = []
    http_calls = 0
    try:
        for cik, group in by_cik.items():
            submissions = client.fetch_submissions(cik, use_cache=True)
            http_calls += 1
            filings = discover_nport_filings(submissions, cik=cik)
            discovered += len(filings)
            needed = {fund.series_id: filings_per_series for fund in group}
            funds_by_series = {fund.series_id: fund for fund in group}
            series_by_fund = {
                f"cik:{fund.cik}|series:{fund.series_id}": fund.series_id for fund in group
            }
            for filing in filings[:SCAN_LIMIT]:
                if not any(count > 0 for count in needed.values()):
                    break
                existing = repository.get_filing(filing.accession)
                if existing is not None and existing.parser_version == PARSER_VERSION:
                    series_id = series_by_fund.get(existing.fund_id)
                    if series_id is not None and needed.get(series_id, 0) > 0:
                        needed[series_id] -= 1
                        reused += 1
                    continue
                try:
                    stored_series = _store_if_target(
                        settings,
                        client,
                        store,
                        repository,
                        filing,
                        funds_by_series,
                    )
                except Exception:
                    failed.append(filing.accession)
                    continue
                http_calls += 1
                if stored_series is None:
                    continue
                downloaded += 1
                parsed += 1
                if needed.get(stored_series, 0) > 0:
                    needed[stored_series] -= 1
                    print(f"stored {funds_by_series[stored_series].ticker}", flush=True)
    finally:
        client.close()
    return {
        "funds_processed": len(targets),
        "filings_discovered": discovered,
        "filings_reused": reused,
        "filings_downloaded": downloaded,
        "filings_parsed": parsed,
        "failures": failed,
        "http_calls_observed": http_calls,
    }


def _store_if_target(
    settings: AppSettings,
    client: SecClient,
    store: LocalHoldingsStore,
    repository: SyncRepository,
    filing: object,
    funds_by_series: dict[str, ResolvedFund],
) -> str | None:
    from etf_genome.data.sources.sec.discovery import DiscoveredFiling

    if not isinstance(filing, DiscoveredFiling):
        return None
    document = filing.primary_document
    if "/" in document or not document.lower().endswith(".xml"):
        index_url = filing_document_url(filing.cik, filing.accession, "index.json")
        chosen = choose_filing_xml(client.get_json(index_url, use_cache=True))
        if chosen is None:
            return None
        document = chosen
    url = filing_document_url(filing.cik, filing.accession, document)
    payload = client.get_bytes(url, use_cache=True)
    parsed = parse_nport_xml(payload, max_bytes=settings.sec_max_response_bytes)
    series = (parsed.series_id or "").upper()
    fund = funds_by_series.get(series)
    if fund is None or parsed.report_date is None:
        return None
    tracked = TrackedFund(
        fund_id=f"cik:{fund.cik}|series:{fund.series_id}",
        ticker=fund.ticker,
        name=fund.fund_name,
        cik=fund.cik,
        series_id=fund.series_id,
        class_id=fund.class_id,
    )
    downloaded_at = datetime.now(UTC).isoformat()
    frame = _with_fund_context(parsed.raw_frame(), tracked, filing, downloaded_at)
    normalized = normalize_holdings(frame, weight_unit="fraction")
    if normalized.frame.is_empty():
        return None
    content_hash = hashlib.sha256(payload).hexdigest()
    metadata = FundMetadata(
        fund_id=tracked.fund_id,
        name=parsed.fund_name or tracked.name,
        ticker=tracked.ticker,
        cik=tracked.cik,
        series_id=tracked.series_id,
        class_id=tracked.class_id,
    )
    store.write_holdings(normalized.frame, metadata)
    repository.record_filing(
        accession=filing.accession,
        fund_id=tracked.fund_id,
        cik=tracked.cik,
        series_id=series,
        class_id=parsed.class_id or tracked.class_id,
        report_date=parsed.report_date.isoformat(),
        filed_at=filing.filed_at,
        primary_document=document,
        source_url=url,
        content_hash=content_hash,
        raw_path="",
        parser_version=PARSER_VERSION,
        downloaded_at=downloaded_at,
        holding_count=normalized.frame.height,
    )
    return series
