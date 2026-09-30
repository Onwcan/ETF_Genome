"""SQLite catalog for fund metadata and snapshot locations.

SQLite holds small application state. Holdings rows themselves live in Parquet.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from etf_genome.domain.models import FundMetadata

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS funds (
    fund_id TEXT PRIMARY KEY,
    name TEXT,
    ticker TEXT,
    cik TEXT,
    series_id TEXT,
    class_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    fund_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    parquet_path TEXT NOT NULL,
    source TEXT,
    holding_count INTEGER NOT NULL,
    accession TEXT,
    filed_at TEXT,
    downloaded_at TEXT,
    content_hash TEXT,
    parser_version TEXT,
    source_url TEXT,
    PRIMARY KEY (fund_id, snapshot_date),
    FOREIGN KEY (fund_id) REFERENCES funds (fund_id)
);

CREATE TABLE IF NOT EXISTS filing_provenance (
    accession TEXT PRIMARY KEY,
    fund_id TEXT NOT NULL,
    cik TEXT NOT NULL,
    series_id TEXT,
    class_id TEXT,
    form_type TEXT NOT NULL,
    report_date TEXT,
    filed_at TEXT,
    primary_document TEXT,
    source_url TEXT,
    content_hash TEXT NOT NULL,
    raw_path TEXT,
    parser_version TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    holding_count INTEGER,
    snapshot_date TEXT
);

CREATE TABLE IF NOT EXISTS dataset_freshness (
    provider TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    source_as_of TEXT,
    source_published_at TEXT,
    downloaded_at TEXT,
    last_checked_at TEXT,
    last_successful_sync_at TEXT,
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT,
    status TEXT,
    error_message TEXT,
    PRIMARY KEY (provider, resource_type, resource_id)
);

CREATE TABLE IF NOT EXISTS sync_state (
    provider TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_seen_remote_item TEXT,
    last_ingested_item TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    next_allowed_attempt TEXT,
    last_error TEXT,
    last_error_class TEXT,
    PRIMARY KEY (provider, entity_id)
);
"""

_SNAPSHOT_COLUMNS = {
    "accession": "TEXT",
    "filed_at": "TEXT",
    "downloaded_at": "TEXT",
    "content_hash": "TEXT",
    "parser_version": "TEXT",
    "source_url": "TEXT",
}


class SqliteCatalog:
    """Metadata catalog stored at one SQLite file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            _ensure_snapshot_columns(connection)
            connection.execute(
                """
                INSERT INTO schema_meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("schema_version", "2"),
            )

    def upsert_fund(self, metadata: FundMetadata) -> None:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO funds (
                    fund_id, name, ticker, cik, series_id, class_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fund_id) DO UPDATE SET
                    name = excluded.name,
                    ticker = excluded.ticker,
                    cik = excluded.cik,
                    series_id = excluded.series_id,
                    class_id = excluded.class_id,
                    updated_at = excluded.updated_at
                """,
                (
                    metadata.fund_id,
                    metadata.name,
                    metadata.ticker,
                    metadata.cik,
                    metadata.series_id,
                    metadata.class_id,
                    updated_at,
                ),
            )

    def get_fund(self, fund_id: str) -> FundMetadata | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT fund_id, name, ticker, cik, series_id, class_id
                FROM funds
                WHERE fund_id = ?
                """,
                (fund_id,),
            ).fetchone()
        if row is None:
            return None
        return FundMetadata(
            fund_id=row["fund_id"],
            name=row["name"],
            ticker=row["ticker"],
            cik=row["cik"],
            series_id=row["series_id"],
            class_id=row["class_id"],
        )

    def upsert_snapshot(
        self,
        *,
        fund_id: str,
        snapshot_date: date,
        parquet_path: Path,
        source: str | None,
        holding_count: int,
        accession: str | None = None,
        filed_at: str | None = None,
        downloaded_at: str | None = None,
        content_hash: str | None = None,
        parser_version: str | None = None,
        source_url: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO snapshots (
                    fund_id, snapshot_date, parquet_path, source, holding_count,
                    accession, filed_at, downloaded_at, content_hash, parser_version, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fund_id, snapshot_date) DO UPDATE SET
                    parquet_path = excluded.parquet_path,
                    source = excluded.source,
                    holding_count = excluded.holding_count,
                    accession = excluded.accession,
                    filed_at = excluded.filed_at,
                    downloaded_at = excluded.downloaded_at,
                    content_hash = excluded.content_hash,
                    parser_version = excluded.parser_version,
                    source_url = excluded.source_url
                """,
                (
                    fund_id,
                    snapshot_date.isoformat(),
                    str(parquet_path),
                    source,
                    holding_count,
                    accession,
                    filed_at,
                    downloaded_at,
                    content_hash,
                    parser_version,
                    source_url,
                ),
            )

    def list_snapshot_dates(self, fund_id: str) -> list[date]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT snapshot_date FROM snapshots WHERE fund_id = ? ORDER BY snapshot_date",
                (fund_id,),
            ).fetchall()
        return [date.fromisoformat(row["snapshot_date"]) for row in rows]

    def connect(self) -> sqlite3.Connection:
        return self._connect()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _ensure_snapshot_columns(connection: sqlite3.Connection) -> None:
    existing = {row[1] for row in connection.execute("PRAGMA table_info(snapshots)")}
    for column, declaration in _SNAPSHOT_COLUMNS.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE snapshots ADD COLUMN {column} {declaration}")
