"""Download and ingest NPORT-P filings for one tracked fund."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.normalization.holdings import normalize_holdings
from etf_genome.data.sources.sec.client import SecClient
from etf_genome.data.sources.sec.discovery import (
    DiscoveredFiling,
    choose_filing_xml,
    discover_nport_filings,
    filing_document_url,
)
from etf_genome.data.sources.sec.nport_xml import PARSER_VERSION, parse_nport_xml
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.domain.funds import QQQ, TrackedFund
from etf_genome.domain.models import FundMetadata
from etf_genome.errors import EtfGenomeError

logger = logging.getLogger(__name__)


class FilingValidationError(EtfGenomeError):
    """Raised when a parsed filing does not belong to the requested fund."""


@dataclass(frozen=True)
class IngestWorkResult:
    """What one SEC synchronization pass changed."""

    discovered: int
    ingested: tuple[str, ...]
    skipped: tuple[str, ...]
    seen: tuple[str, ...]
    report_dates: tuple[str, ...]
    changed: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)
    failed: tuple[str, ...] = ()


class SecNportSync:
    """Discover, download, parse, and store NPORT-P filings for one fund."""

    def __init__(
        self,
        settings: AppSettings,
        client: SecClient,
        store: LocalHoldingsStore,
        repository: SyncRepository,
        fund: TrackedFund = QQQ,
    ) -> None:
        self._settings = settings
        self._client = client
        self._store = store
        self._repository = repository
        self._fund = fund

    def close(self) -> None:
        self._client.close()

    def run(
        self,
        *,
        cancelled: Callable[[], bool] | None = None,
        max_filings: int | None = None,
        continue_on_error: bool = False,
    ) -> IngestWorkResult:
        stop = cancelled or (lambda: False)
        payload = self._client.fetch_submissions(self._fund.cik, use_cache=False)
        if stop():
            return _empty()
        discovered = discover_nport_filings(payload, cik=self._fund.cik)
        limit = self._settings.sec_max_filings_per_sync if max_filings is None else max_filings
        if limit < 1 or limit > 40:
            raise ValueError("max_filings must be between 1 and 40")
        selected = discovered[:limit]
        ingested: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []
        seen: list[str] = []
        warnings: list[str] = []
        for filing in selected:
            if stop():
                break
            seen.append(filing.accession)
            if self._already_stored(filing):
                skipped.append(filing.accession)
                logger.info(
                    "Skipping stored SEC filing",
                    extra={
                        "provider": "sec",
                        "fund_id": self._fund.fund_id,
                        "cik": self._fund.cik,
                        "accession": filing.accession,
                        "operation": "skip",
                        "result": "cached",
                    },
                )
                continue
            try:
                self._ingest_one(filing, warnings)
            except EtfGenomeError:
                if not continue_on_error:
                    raise
                failed.append(filing.accession)
                logger.warning(
                    "SEC filing was not stored",
                    extra={
                        "provider": "sec",
                        "fund_id": self._fund.fund_id,
                        "accession": filing.accession,
                        "operation": "ingest",
                        "result": "failed",
                    },
                )
                continue
            ingested.append(filing.accession)
        report_dates = tuple(
            filing.report_date for filing in selected if filing.report_date is not None
        )
        return IngestWorkResult(
            discovered=len(discovered),
            ingested=tuple(ingested),
            skipped=tuple(skipped),
            seen=tuple(seen),
            report_dates=report_dates,
            changed=bool(ingested),
            warnings=tuple(warnings),
            failed=tuple(failed),
        )

    def _already_stored(self, filing: DiscoveredFiling) -> bool:
        existing = self._repository.get_filing(filing.accession)
        if existing is None or existing.fund_id != self._fund.fund_id:
            return False
        return existing.parser_version == PARSER_VERSION

    def _ingest_one(self, filing: DiscoveredFiling, warnings: list[str]) -> None:
        document = self._xml_document_name(filing)
        url = filing_document_url(self._fund.cik, filing.accession, document)
        started = datetime.now(UTC)
        payload = self._client.get_bytes(url, use_cache=False)
        if _looks_like_html(payload):
            raise FilingValidationError(
                f"Filing {filing.accession} returned HTML instead of N-PORT XML. "
                "The previous snapshot was not replaced."
            )
        elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        logger.info(
            "Downloaded SEC filing",
            extra={
                "provider": "sec",
                "fund_id": self._fund.fund_id,
                "cik": self._fund.cik,
                "accession": filing.accession,
                "operation": "download",
                "elapsed_ms": elapsed_ms,
                "download_bytes": len(payload),
                "result": "ok",
            },
        )
        parsed = parse_nport_xml(payload, max_bytes=self._settings.sec_max_response_bytes)
        self._require_same_fund(parsed.cik, parsed.series_id, filing.accession)
        warnings.extend(parsed.warnings)
        downloaded_at = datetime.now(UTC).isoformat()
        frame = _with_fund_context(parsed.raw_frame(), self._fund, filing, downloaded_at)
        normalized = normalize_holdings(frame, weight_unit="fraction")
        if normalized.frame.is_empty():
            raise FilingValidationError(f"Filing {filing.accession} normalized to no holdings")
        weight_sum = _weight_sum(normalized.frame)
        if weight_sum is not None and (weight_sum < 0 or weight_sum > 5):
            raise FilingValidationError(
                f"Filing {filing.accession} weight sum {weight_sum:.4f} is outside sanity bounds. "
                "The previous snapshot was not replaced."
            )
        warnings.extend(normalized.warnings)
        if weight_sum is not None and (weight_sum < 0.5 or weight_sum > 1.5):
            warnings.append(
                f"Filing {filing.accession} observed weight sum is {weight_sum:.4f}. "
                "Values were not rescaled."
            )
        content_hash = hashlib.sha256(payload).hexdigest()
        raw_path = ""
        if self._settings.remote_cache_enabled:
            raw_path = str(_write_raw(self._settings, self._fund.cik, filing.accession, payload))
        metadata = FundMetadata(
            fund_id=self._fund.fund_id,
            name=parsed.fund_name or self._fund.name,
            ticker=self._fund.ticker,
            cik=self._fund.cik,
            series_id=self._fund.series_id,
            class_id=self._fund.class_id,
        )
        self._store.write_holdings(normalized.frame, metadata)
        self._store.catalog.upsert_snapshot(
            fund_id=self._fund.fund_id,
            snapshot_date=parsed.report_date,
            parquet_path=self._store.parquet.path_for(self._fund.fund_id, parsed.report_date),
            source=f"sec-nport:{filing.accession}",
            holding_count=normalized.frame.height,
            accession=filing.accession,
            filed_at=filing.filed_at,
            downloaded_at=downloaded_at,
            content_hash=content_hash,
            parser_version=PARSER_VERSION,
            source_url=url,
        )
        self._repository.record_filing(
            accession=filing.accession,
            fund_id=self._fund.fund_id,
            cik=self._fund.cik,
            series_id=parsed.series_id or self._fund.series_id,
            class_id=parsed.class_id or self._fund.class_id,
            report_date=parsed.report_date.isoformat(),
            filed_at=filing.filed_at,
            primary_document=document,
            source_url=url,
            content_hash=content_hash,
            raw_path=raw_path,
            parser_version=PARSER_VERSION,
            downloaded_at=downloaded_at,
            holding_count=normalized.frame.height,
        )

    def _require_same_fund(self, cik: str | None, series_id: str | None, accession: str) -> None:
        if cik is not None and _digits(cik) != _digits(self._fund.cik):
            raise FilingValidationError(
                f"Filing {accession} CIK does not match {self._fund.ticker}"
            )
        if series_id is not None and series_id.upper() != self._fund.series_id.upper():
            raise FilingValidationError(
                f"Filing {accession} series does not match {self._fund.ticker}"
            )

    def _xml_document_name(self, filing: DiscoveredFiling) -> str:
        # A submissions path such as xslFormNPORT-P_X01/primary_doc.xml is the
        # rendered filing view. The raw XML name comes from the filing index.
        direct = "/" not in filing.primary_document and filing.primary_document.lower().endswith(
            ".xml"
        )
        if direct:
            return filing.primary_document
        index_url = filing_document_url(self._fund.cik, filing.accession, "index.json")
        payload = self._client.get_json(index_url, use_cache=False)
        chosen = choose_filing_xml(payload)
        if chosen is None:
            raise FilingValidationError(
                f"Filing {filing.accession} does not contain an XML document"
            )
        return chosen


def _with_fund_context(
    frame: pl.DataFrame,
    fund: TrackedFund,
    filing: DiscoveredFiling,
    downloaded_at: str,
) -> pl.DataFrame:
    filed = filing.filed_at
    source_timestamp = f"{filed}T00:00:00+00:00" if filed else downloaded_at
    return frame.with_columns(
        pl.lit(fund.fund_id).alias("fund_id"),
        pl.lit(fund.name).alias("fund_name"),
        pl.lit(fund.ticker).alias("ticker"),
        pl.lit(fund.cik).alias("cik"),
        pl.lit(fund.series_id).alias("series_id"),
        pl.lit(fund.class_id).alias("class_id"),
        pl.lit(f"sec-nport:{filing.accession}").alias("source"),
        pl.lit(source_timestamp).alias("source_timestamp"),
    )


def _looks_like_html(payload: bytes) -> bool:
    start = payload.lstrip()[:300].lower()
    return start.startswith(b"<!doctype html") or start.startswith(b"<html")


def _weight_sum(frame: pl.DataFrame) -> float | None:
    values = [
        float(value)
        for value in frame.get_column("portfolio_weight").to_list()
        if value is not None
    ]
    if not values:
        return None
    return float(sum(values))


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _write_raw(settings: AppSettings, cik: str, accession: str, payload: bytes) -> Path:
    directory = settings.cache_dir / "sec" / "nport" / cik / accession.replace("-", "")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "primary.xml"
    temporary = directory / "primary.xml.tmp"
    temporary.write_bytes(payload)
    temporary.replace(target)
    return target


def _empty() -> IngestWorkResult:
    return IngestWorkResult(
        discovered=0,
        ingested=(),
        skipped=(),
        seen=(),
        report_dates=(),
        changed=False,
    )
