"""SQLite records for filings, freshness, and provider sync state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from etf_genome.data.storage.sqlite_catalog import SqliteCatalog


@dataclass(frozen=True)
class FilingRecord:
    """Provenance for one ingested accession."""

    accession: str
    fund_id: str
    content_hash: str
    report_date: str | None
    filed_at: str | None
    downloaded_at: str | None
    raw_path: str | None
    parser_version: str | None


@dataclass(frozen=True)
class SyncStateRecord:
    """Last attempt and backoff for one provider entity."""

    provider: str
    entity_id: str
    last_attempt_at: str | None
    last_success_at: str | None
    last_seen_remote_item: str | None
    last_ingested_item: str | None
    consecutive_failures: int
    next_allowed_attempt: str | None
    last_error: str | None
    last_error_class: str | None


class SyncRepository:
    """Read and write synchronization metadata in the catalog database."""

    def __init__(self, catalog: SqliteCatalog) -> None:
        self._catalog = catalog
        catalog.initialize()

    def get_filing(self, accession: str) -> FilingRecord | None:
        with self._catalog.connect() as connection:
            row = connection.execute(
                """
                SELECT accession, fund_id, content_hash, report_date, filed_at,
                       downloaded_at, raw_path, parser_version
                FROM filing_provenance
                WHERE accession = ?
                """,
                (accession,),
            ).fetchone()
        if row is None:
            return None
        return FilingRecord(
            accession=row["accession"],
            fund_id=row["fund_id"],
            content_hash=row["content_hash"],
            report_date=row["report_date"],
            filed_at=row["filed_at"],
            downloaded_at=row["downloaded_at"],
            raw_path=row["raw_path"],
            parser_version=row["parser_version"],
        )

    def list_filings(self, fund_id: str) -> list[FilingRecord]:
        with self._catalog.connect() as connection:
            rows = connection.execute(
                """
                SELECT accession, fund_id, content_hash, report_date, filed_at,
                       downloaded_at, raw_path, parser_version
                FROM filing_provenance
                WHERE fund_id = ?
                ORDER BY report_date, accession
                """,
                (fund_id,),
            ).fetchall()
        return [
            FilingRecord(
                accession=row["accession"],
                fund_id=row["fund_id"],
                content_hash=row["content_hash"],
                report_date=row["report_date"],
                filed_at=row["filed_at"],
                downloaded_at=row["downloaded_at"],
                raw_path=row["raw_path"],
                parser_version=row["parser_version"],
            )
            for row in rows
        ]

    def record_filing(
        self,
        *,
        accession: str,
        fund_id: str,
        cik: str,
        series_id: str | None,
        class_id: str | None,
        report_date: str,
        filed_at: str | None,
        primary_document: str,
        source_url: str,
        content_hash: str,
        raw_path: str,
        parser_version: str,
        downloaded_at: str,
        holding_count: int,
    ) -> None:
        with self._catalog.connect() as connection:
            connection.execute(
                """
                INSERT INTO filing_provenance (
                    accession, fund_id, cik, series_id, class_id, form_type, report_date,
                    filed_at, primary_document, source_url, content_hash, raw_path,
                    parser_version, downloaded_at, holding_count, snapshot_date
                ) VALUES (?, ?, ?, ?, ?, 'NPORT-P', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(accession) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    raw_path = excluded.raw_path,
                    downloaded_at = excluded.downloaded_at,
                    holding_count = excluded.holding_count,
                    parser_version = excluded.parser_version,
                    source_url = excluded.source_url
                """,
                (
                    accession,
                    fund_id,
                    cik,
                    series_id,
                    class_id,
                    report_date,
                    filed_at,
                    primary_document,
                    source_url,
                    content_hash,
                    raw_path,
                    parser_version,
                    downloaded_at,
                    holding_count,
                    report_date,
                ),
            )

    def get_sync_state(self, provider: str, entity_id: str) -> SyncStateRecord | None:
        with self._catalog.connect() as connection:
            row = connection.execute(
                """
                SELECT provider, entity_id, last_attempt_at, last_success_at,
                       last_seen_remote_item, last_ingested_item, consecutive_failures,
                       next_allowed_attempt, last_error, last_error_class
                FROM sync_state
                WHERE provider = ? AND entity_id = ?
                """,
                (provider, entity_id),
            ).fetchone()
        if row is None:
            return None
        return SyncStateRecord(
            provider=row["provider"],
            entity_id=row["entity_id"],
            last_attempt_at=row["last_attempt_at"],
            last_success_at=row["last_success_at"],
            last_seen_remote_item=row["last_seen_remote_item"],
            last_ingested_item=row["last_ingested_item"],
            consecutive_failures=int(row["consecutive_failures"]),
            next_allowed_attempt=row["next_allowed_attempt"],
            last_error=row["last_error"],
            last_error_class=row["last_error_class"],
        )

    def save_sync_state(self, record: SyncStateRecord) -> None:
        with self._catalog.connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_state (
                    provider, entity_id, last_attempt_at, last_success_at,
                    last_seen_remote_item, last_ingested_item, consecutive_failures,
                    next_allowed_attempt, last_error, last_error_class
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, entity_id) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at,
                    last_success_at = excluded.last_success_at,
                    last_seen_remote_item = excluded.last_seen_remote_item,
                    last_ingested_item = excluded.last_ingested_item,
                    consecutive_failures = excluded.consecutive_failures,
                    next_allowed_attempt = excluded.next_allowed_attempt,
                    last_error = excluded.last_error,
                    last_error_class = excluded.last_error_class
                """,
                (
                    record.provider,
                    record.entity_id,
                    record.last_attempt_at,
                    record.last_success_at,
                    record.last_seen_remote_item,
                    record.last_ingested_item,
                    record.consecutive_failures,
                    record.next_allowed_attempt,
                    record.last_error,
                    record.last_error_class,
                ),
            )

    def save_freshness(
        self,
        *,
        provider: str,
        resource_type: str,
        resource_id: str,
        source_as_of: str | None,
        source_published_at: str | None,
        downloaded_at: str | None,
        last_checked_at: str | None,
        last_successful_sync_at: str | None,
        content_hash: str | None,
        status: str,
        error_message: str | None,
    ) -> None:
        with self._catalog.connect() as connection:
            connection.execute(
                """
                INSERT INTO dataset_freshness (
                    provider, resource_type, resource_id, source_as_of, source_published_at,
                    downloaded_at, last_checked_at, last_successful_sync_at, content_hash,
                    status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, resource_type, resource_id) DO UPDATE SET
                    source_as_of = excluded.source_as_of,
                    source_published_at = excluded.source_published_at,
                    downloaded_at = excluded.downloaded_at,
                    last_checked_at = excluded.last_checked_at,
                    last_successful_sync_at = excluded.last_successful_sync_at,
                    content_hash = excluded.content_hash,
                    status = excluded.status,
                    error_message = excluded.error_message
                """,
                (
                    provider,
                    resource_type,
                    resource_id,
                    source_as_of,
                    source_published_at,
                    downloaded_at,
                    last_checked_at,
                    last_successful_sync_at,
                    content_hash,
                    status,
                    error_message,
                ),
            )


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    return datetime.fromisoformat(value)
