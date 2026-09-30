"""Local storage round-trip tests."""

from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.data.normalization.holdings import normalize_holdings
from etf_genome.data.storage.errors import StorageError
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.parquet_store import safe_fund_dirname
from etf_genome.domain.models import FundMetadata


def _normalized() -> pl.DataFrame:
    raw = pl.DataFrame(
        {
            "snapshot_date": ["2024-06-30", "2024-06-30", "2025-06-30"],
            "fund_id": ["FUND-1", "FUND-1", "FUND-1"],
            "fund_name": ["Demo Fund", "Demo Fund", "Demo Fund"],
            "ticker": ["DEMO", "DEMO", "DEMO"],
            "cik": ["0001999999", "0001999999", "0001999999"],
            "series_id": ["S000099999", "S000099999", "S000099999"],
            "security_name": ["Alpha", "Beta", "Alpha"],
            "cusip": ["ALPH00010", "BETA00010", "ALPH00010"],
            "isin": ["USALPH000104", None, "USALPH000104"],
            "sector": ["Technology", None, "Technology"],
            "industry": ["Software", "Banks", None],
            "country": ["US", "US", "US"],
            "portfolio_weight": [0.25, 0.75, 1.0],
            "market_value": [25.0, 75.0, 100.0],
            "quantity": [1.0, 3.0, 4.0],
            "source": ["unit", "unit", "unit"],
        }
    )
    return normalize_holdings(raw).frame


def test_unsafe_fund_ids_are_rejected() -> None:
    with pytest.raises(StorageError):
        safe_fund_dirname("../secret")
    with pytest.raises(StorageError):
        safe_fund_dirname("a/b")
    assert safe_fund_dirname("cik:0001999999|series:S1") == "cik_0001999999_series_S1"


def test_parquet_sqlite_and_duckdb_round_trip(settings: AppSettings) -> None:
    frame = _normalized()
    store = LocalHoldingsStore(settings)
    metadata = FundMetadata(
        fund_id="FUND-1",
        name="Demo Fund",
        ticker="DEMO",
        cik="0001999999",
        series_id="S000099999",
    )
    paths = store.write_holdings(frame, metadata)
    assert len(paths) == 2

    restored = store.read_holdings("FUND-1", date(2024, 6, 30))
    beta = restored.filter(pl.col("security_id") == "cusip:BETA00010").row(0, named=True)
    assert beta["isin"] is None
    assert beta["sector"] is None
    assert beta["portfolio_weight"] == pytest.approx(0.75)
    assert beta["industry"] == "Banks"

    stored_fund = store.catalog.get_fund("FUND-1")
    assert stored_fund is not None
    assert stored_fund.ticker == "DEMO"
    assert store.catalog.list_snapshot_dates("FUND-1") == [
        date(2024, 6, 30),
        date(2025, 6, 30),
    ]

    summary, engine = store.summarize()
    assert engine in {"duckdb", "polars_fallback"}
    counts = {
        _as_date(row["snapshot_date"]): row["holding_count"]
        for row in summary.iter_rows(named=True)
    }
    assert counts[date(2024, 6, 30)] == 2
    assert counts[date(2025, 6, 30)] == 1
    weight_sums = {
        _as_date(row["snapshot_date"]): row["weight_sum"] for row in summary.iter_rows(named=True)
    }
    assert weight_sums[date(2024, 6, 30)] == pytest.approx(1.0)


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
