"""CLI entry for the same QQQ synchronization path the desktop uses."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.sec.nport_xml import parse_nport_xml
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.domain.funds import QQQ
from etf_genome.errors import EtfGenomeError
from etf_genome.logging_config import configure_logging
from etf_genome.services.fund_view import build_fund_view
from etf_genome.services.runtime import build_update_coordinator


def main() -> int:
    """Discover and ingest missing QQQ NPORT-P filings, then print the local view."""

    settings = AppSettings()
    logger = configure_logging(settings)
    try:
        coordinator = None
        if not settings.offline_mode:
            coordinator = build_update_coordinator(settings)
            try:
                outcome = coordinator.sync_sec("manual")
            finally:
                coordinator.close()
        else:
            outcome = None
        view = build_fund_view(settings)
    except EtfGenomeError as exc:
        logger.error("%s", exc)
        print("ETF Genome could not synchronize SEC filings.", file=sys.stderr)
        return 1
    payload = {
        "sync": None
        if outcome is None
        else {
            "status": outcome.status,
            "changed": outcome.changed,
            "message": outcome.message,
            "filings_discovered": outcome.filings_discovered,
            "filings_ingested": outcome.filings_ingested,
            "filings_skipped": outcome.filings_skipped,
            "report_dates": list(outcome.report_dates),
            "accessions": list(outcome.accessions),
            "error_class": outcome.error_class,
        },
        "view": {
            "fund": view.fund_name,
            "ticker": view.ticker,
            "holdings_as_of": None
            if view.holdings_as_of is None
            else view.holdings_as_of.isoformat(),
            "published_at": view.published_at,
            "downloaded_at": view.downloaded_at,
            "last_checked_at": view.last_checked_at,
            "freshness": view.freshness,
            "holdings": view.holdings_count,
            "top_10_weight": view.top_10_weight,
            "hhi": view.hhi,
            "drift": view.drift_value,
            "drift_metric": view.drift_metric,
            "from_date": None if view.from_date is None else view.from_date.isoformat(),
            "to_date": None if view.to_date is None else view.to_date.isoformat(),
            "message": view.status_message,
        },
        "quality": _quality(settings),
    }
    print(json.dumps(payload, indent=2))
    if outcome is not None and outcome.error_class is not None:
        return 1
    return 0


def _quality(settings: AppSettings) -> dict[str, object]:
    store = LocalHoldingsStore(settings)
    filings = SyncRepository(store.catalog).list_filings(QQQ.fund_id)
    rows: list[dict[str, object]] = []
    for filing in filings:
        if filing.report_date is None:
            continue
        frame = store.read_holdings(QQQ.fund_id, date.fromisoformat(filing.report_date))
        weights = [
            float(value)
            for value in frame.get_column("portfolio_weight").to_list()
            if value is not None
        ]
        rows.append(
            {
                "accession": filing.accession,
                "report_date": filing.report_date,
                "filed_at": filing.filed_at,
                "downloaded_at": filing.downloaded_at,
                "sha256_prefix": (filing.content_hash or "")[:12],
                "parser_version": filing.parser_version,
                "normalized_rows": frame.height,
                "weight_sum": None if not weights else float(sum(weights)),
                "with_market_value": _count_present(frame, "market_value"),
                "with_weight": len(weights),
                "with_cusip": _count_present(frame, "cusip"),
                "with_isin": _count_present(frame, "isin"),
                "with_currency": _count_present(frame, "currency"),
                "with_country": _count_present(frame, "country"),
                "with_asset_type": _count_present(frame, "asset_type"),
                "id_methods": _id_methods(frame),
                "largest": _largest(frame),
                "audit_issues": _audit(filing.raw_path, frame, settings),
            }
        )
    return {"snapshots": rows}


def _count_present(frame: pl.DataFrame, column: str) -> int:
    return sum(
        value is not None and str(value).strip() != ""
        for value in frame.get_column(column).to_list()
    )


def _id_methods(frame: pl.DataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in frame.get_column("security_id").to_list():
        prefix = str(value).split(":", 1)[0]
        counts[prefix] = counts.get(prefix, 0) + 1
    return counts


def _largest(frame: pl.DataFrame) -> list[dict[str, object]]:
    ranked = frame.sort(
        ["portfolio_weight", "security_id"],
        descending=[True, False],
        nulls_last=True,
    ).head(10)
    items: list[dict[str, object]] = []
    for row in ranked.iter_rows(named=True):
        items.append(
            {
                "name": row.get("security_name"),
                "cusip": row.get("cusip"),
                "weight": row.get("portfolio_weight"),
                "market_value": row.get("market_value"),
            }
        )
    return items


def _audit(raw_path: str | None, frame: pl.DataFrame, settings: AppSettings) -> list[str]:
    if not raw_path:
        return ["raw artifact path is missing"]
    path = Path(raw_path)
    if not path.is_file():
        return ["raw artifact file is missing"]
    parsed = parse_nport_xml(path.read_bytes(), max_bytes=settings.sec_max_response_bytes)
    by_cusip = {str(row["cusip"]): row for row in parsed.rows if row.get("cusip")}
    issues: list[str] = []
    for item in _largest(frame):
        cusip = item["cusip"]
        if not cusip:
            issues.append(f"largest position {item['name']} has no CUSIP to audit")
            continue
        source = by_cusip.get(str(cusip))
        if source is None:
            issues.append(f"CUSIP {cusip} was not a direct position field in the XML")
            continue
        if source.get("security_name") != item["name"]:
            issues.append(f"name mismatch for {cusip}")
        if source.get("portfolio_weight") != item["weight"]:
            left = source.get("portfolio_weight")
            right = item["weight"]
            if (
                not isinstance(left, float)
                or not isinstance(right, float)
                or abs(left - right) > 1e-8
            ):
                issues.append(f"weight mismatch for {cusip}")
        if source.get("market_value") != item["market_value"]:
            left = source.get("market_value")
            right = item["market_value"]
            if (
                not isinstance(left, float)
                or not isinstance(right, float)
                or abs(left - right) > 0.01
            ):
                issues.append(f"market value mismatch for {cusip}")
    return issues
