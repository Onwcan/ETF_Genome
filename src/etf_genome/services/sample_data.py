"""Load the deterministic sample holdings payload and normalize it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from etf_genome.config.paths import sample_holdings_path
from etf_genome.data.normalization.holdings import (
    NormalizationResult,
    concatenate_results,
    normalize_holdings,
)
from etf_genome.domain.models import FundMetadata
from etf_genome.errors import EtfGenomeError


class SampleDataError(EtfGenomeError):
    """Raised when the sample payload is not usable."""


def load_sample_payload(path: Path | None = None) -> dict[str, Any]:
    """Read the synthetic holdings fixture. This file is not a market download."""

    source = path or sample_holdings_path()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SampleDataError(f"Sample holdings file is not valid JSON: {source}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshots"), list):
        raise SampleDataError("Sample holdings payload must contain a snapshots list")
    if len(payload["snapshots"]) < 2:
        raise SampleDataError("Sample holdings payload needs at least two snapshots")
    return payload


def normalize_payload(payload: dict[str, Any]) -> NormalizationResult:
    """Normalize every snapshot in a fixture payload."""

    results = []
    for index, snapshot in enumerate(payload["snapshots"]):
        if not isinstance(snapshot, dict):
            raise SampleDataError(f"Snapshot {index} is not an object")
        weight_unit = snapshot.get("weight_unit", "fraction")
        if weight_unit not in {"fraction", "percent"}:
            raise SampleDataError(f"Snapshot {index} has an unknown weight_unit")
        results.append(normalize_holdings(_snapshot_frame(snapshot), weight_unit=weight_unit))
    return concatenate_results(results)


def metadata_from_frame(frame: pl.DataFrame) -> FundMetadata:
    """Build catalog metadata from a normalized one-fund frame."""

    fund_ids = [value for value in frame.get_column("fund_id").unique().to_list() if value]
    if len(fund_ids) != 1:
        raise SampleDataError("The normalized sample must contain exactly one fund_id")

    def first_text(column: str) -> str | None:
        if column not in frame.columns:
            return None
        for value in frame.get_column(column).to_list():
            if value is not None and str(value).strip():
                return str(value)
        return None

    return FundMetadata(
        fund_id=str(fund_ids[0]),
        name=first_text("fund_name"),
        ticker=first_text("ticker"),
        cik=first_text("cik"),
        series_id=first_text("series_id"),
        class_id=first_text("class_id"),
    )


def _snapshot_frame(snapshot: dict[str, Any]) -> pl.DataFrame:
    holdings = snapshot.get("holdings")
    if not isinstance(holdings, list) or not holdings:
        raise SampleDataError("Each snapshot needs a non-empty holdings list")
    shared = {
        "snapshot_date": snapshot.get("snapshot_date"),
        "fund_id": snapshot.get("fund_id"),
        "fund_name": snapshot.get("fund_name"),
        "ticker": snapshot.get("ticker"),
        "cik": snapshot.get("cik"),
        "series_id": snapshot.get("series_id"),
        "class_id": snapshot.get("class_id"),
        "source": snapshot.get("source", "fixture"),
        "source_timestamp": snapshot.get("source_timestamp"),
        "currency": snapshot.get("currency"),
    }
    rows: list[dict[str, Any]] = []
    for holding in holdings:
        if not isinstance(holding, dict):
            raise SampleDataError("Each holding must be an object")
        row = dict(shared)
        row.update(holding)
        rows.append(row)
    return pl.DataFrame(rows)
