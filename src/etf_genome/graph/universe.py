"""Resolve a curated ETF ticker list from the official SEC series/class catalogue."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

_PLACEHOLDERS = {"N/A", "NA", "NONE", "NULL", "NAN", "-", "--", "UNKNOWN"}


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    category: str
    enabled: bool
    reason: str


@dataclass(frozen=True)
class ResolvedFund:
    ticker: str
    category: str
    reason: str
    cik: str
    series_id: str
    class_id: str
    fund_name: str
    status: str


def load_universe_entries(path: Path) -> tuple[str, tuple[UniverseEntry, ...]]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    universe_id = str(payload["universe_id"]).strip()
    entries = tuple(
        UniverseEntry(
            ticker=str(item["ticker"]).strip().upper(),
            category=str(item["category"]).strip(),
            enabled=bool(item.get("enabled", True)),
            reason=str(item.get("reason", "")).strip(),
        )
        for item in payload["funds"]
    )
    tickers = [item.ticker for item in entries if item.enabled]
    if len(tickers) != len(set(tickers)):
        raise ValueError("Enabled universe tickers must be unique.")
    return universe_id, entries


def parse_series_class_frame(payload: object) -> pl.DataFrame:
    """Normalize the SEC series/class catalogue into one row per class ticker."""

    rows = _catalogue_rows(payload)
    if not rows:
        return pl.DataFrame(
            schema={
                "ticker": pl.Utf8,
                "cik": pl.Utf8,
                "series_id": pl.Utf8,
                "class_id": pl.Utf8,
                "fund_name": pl.Utf8,
            }
        )
    frame = pl.DataFrame(rows)
    return frame.unique(subset=["ticker", "cik", "series_id", "class_id"]).sort("ticker")


def resolve_universe(
    entries: tuple[UniverseEntry, ...],
    catalogue: pl.DataFrame,
) -> list[ResolvedFund]:
    resolved: list[ResolvedFund] = []
    for entry in entries:
        if not entry.enabled:
            continue
        matches = catalogue.filter(pl.col("ticker") == entry.ticker)
        if matches.is_empty():
            resolved.append(
                ResolvedFund(
                    entry.ticker,
                    entry.category,
                    entry.reason,
                    "",
                    "",
                    "",
                    "",
                    "unresolved",
                )
            )
            continue
        distinct = matches.select(["cik", "series_id", "class_id"]).unique()
        if distinct.height != 1:
            resolved.append(
                ResolvedFund(
                    entry.ticker,
                    entry.category,
                    entry.reason,
                    "",
                    "",
                    "",
                    "",
                    "ambiguous",
                )
            )
            continue
        row = matches.row(0, named=True)
        resolved.append(
            ResolvedFund(
                ticker=entry.ticker,
                category=entry.category,
                reason=entry.reason,
                cik=_pad_cik(str(row["cik"])),
                series_id=str(row["series_id"]).upper(),
                class_id=str(row["class_id"]).upper(),
                fund_name=str(row["fund_name"] or entry.ticker),
                status="resolved",
            )
        )
    return resolved


def universe_manifest(
    universe_id: str,
    funds: list[ResolvedFund],
    *,
    source_url: str,
    source_bytes: int,
) -> dict[str, object]:
    enabled = [fund for fund in funds if fund.status == "resolved"]
    body = {
        "universe_id": universe_id,
        "funds": [
            {
                "ticker": fund.ticker,
                "category": fund.category,
                "cik": fund.cik,
                "series_id": fund.series_id,
                "class_id": fund.class_id,
                "fund_name": fund.fund_name,
                "status": fund.status,
            }
            for fund in funds
        ],
        "source_url": source_url,
    }
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    complete = bool(enabled) and all(fund.status == "resolved" for fund in funds)
    return {
        **body,
        "created_at": datetime.now(UTC).isoformat(),
        "etf_count": len(enabled),
        "ticker_count": len(funds),
        "resolved_count": len(enabled),
        "unresolved_count": sum(fund.status == "unresolved" for fund in funds),
        "ambiguous_count": sum(fund.status == "ambiguous" for fund in funds),
        "validation_status": "PASSED" if complete else "INCOMPLETE",
        "source_bytes": source_bytes,
        "universe_fingerprint": fingerprint,
    }


def _catalogue_rows(payload: object) -> list[dict[str, str]]:
    if isinstance(payload, pl.DataFrame):
        return _rows_from_frame(payload)
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        fields = [str(item) for item in payload.get("fields", [])]
        rows: list[dict[str, str]] = []
        for item in payload["data"]:
            if not isinstance(item, list):
                continue
            record = {fields[index]: item[index] for index in range(min(len(fields), len(item)))}
            parsed = _row_from_mapping(record)
            if parsed is not None:
                rows.append(parsed)
        return rows
    if isinstance(payload, dict):
        rows = []
        for value in payload.values():
            if isinstance(value, dict):
                parsed = _row_from_mapping(value)
                if parsed is not None:
                    rows.append(parsed)
        return rows
    if isinstance(payload, list):
        rows = []
        for value in payload:
            if isinstance(value, dict):
                parsed = _row_from_mapping(value)
                if parsed is not None:
                    rows.append(parsed)
        return rows
    raise TypeError("SEC series/class catalogue has an unsupported shape.")


def _rows_from_frame(frame: pl.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in frame.iter_rows(named=True):
        parsed = _row_from_mapping({str(key): value for key, value in record.items()})
        if parsed is not None:
            rows.append(parsed)
    return rows


def _row_from_mapping(record: dict[str, object]) -> dict[str, str] | None:
    lowered = {str(key).strip().lower().replace(" ", "_"): value for key, value in record.items()}
    ticker = _text(
        lowered.get("symbol")
        or lowered.get("ticker")
        or lowered.get("class_ticker")
        or lowered.get("classtickersymbol")
    )
    cik = _text(lowered.get("cik") or lowered.get("cik_number"))
    series_id = _text(lowered.get("seriesid") or lowered.get("series_id"))
    class_id = _text(lowered.get("classid") or lowered.get("class_id"))
    name = _text(
        lowered.get("seriesname")
        or lowered.get("series_name")
        or lowered.get("classname")
        or lowered.get("class_name")
        or lowered.get("fund_name")
    )
    if ticker is None or cik is None or series_id is None or class_id is None:
        return None
    if ticker in _PLACEHOLDERS:
        return None
    return {
        "ticker": ticker,
        "cik": _pad_cik(cik),
        "series_id": series_id.upper(),
        "class_id": class_id.upper(),
        "fund_name": name or ticker,
    }


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _pad_cik(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    return digits.zfill(10) if digits else value.strip().upper()
