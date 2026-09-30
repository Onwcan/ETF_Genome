"""Holdings normalization tests."""

from __future__ import annotations

import polars as pl
import pytest

from etf_genome.data.normalization.holdings import CANONICAL_COLUMNS, normalize_holdings
from etf_genome.data.normalization.nport import frame_from_nport_like
from etf_genome.errors import EtfGenomeError


def _raw(**overrides: object) -> pl.DataFrame:
    row: dict[str, object] = {
        "snapshot_date": "2024-06-30",
        "fund_id": "FUND-1",
        "fund_name": "Demo Fund",
        "ticker": "DEMO",
        "security_name": "Alpha",
        "security_ticker": "ALPH",
        "cusip": "ALPH00010",
        "isin": "USALPH000104",
        "asset_type": "equity",
        "sector": "Technology",
        "industry": "Software",
        "country": "US",
        "quantity": 10,
        "market_value": 100.0,
        "portfolio_weight": 0.25,
        "currency": "USD",
        "source": "unit",
        "source_timestamp": "2024-08-01T00:00:00+00:00",
    }
    row.update(overrides)
    return pl.DataFrame([row])


def test_canonical_columns_include_the_phase1_contract() -> None:
    expected = {
        "snapshot_date",
        "fund_id",
        "fund_name",
        "ticker",
        "security_id",
        "security_name",
        "cusip",
        "isin",
        "asset_type",
        "sector",
        "industry",
        "country",
        "quantity",
        "market_value",
        "portfolio_weight",
        "currency",
        "source",
        "source_timestamp",
    }
    assert expected.issubset(CANONICAL_COLUMNS)


def test_percent_weights_are_converted_and_missing_isin_stays_null() -> None:
    frame = _raw(isin=None, portfolio_weight=20)
    result = normalize_holdings(frame, weight_unit="percent")
    row = result.frame.row(0, named=True)
    assert row["portfolio_weight"] == pytest.approx(0.2)
    assert row["isin"] is None
    assert row["security_id"] == "cusip:ALPH00010"
    assert row["sector"] == "Technology"


def test_missing_isin_is_not_invented() -> None:
    result = normalize_holdings(_raw(isin=None))
    assert result.frame.get_column("isin").to_list() == [None]


def test_duplicate_identifiers_are_summed() -> None:
    raw = pl.DataFrame(
        {
            "snapshot_date": ["2024-06-30", "2024-06-30"],
            "fund_id": ["FUND-1", "FUND-1"],
            "security_name": ["Alpha", "Alpha"],
            "cusip": ["ALPH00010", "alph00010"],
            "sector": ["Technology", "Technology"],
            "quantity": [1.0, 2.0],
            "market_value": [10.0, 20.0],
            "portfolio_weight": [0.1, 0.2],
            "source": ["unit", "unit"],
        }
    )
    result = normalize_holdings(raw)
    assert result.rows_out == 1
    assert result.duplicate_rows_merged == 1
    row = result.frame.row(0, named=True)
    assert row["quantity"] == pytest.approx(3.0)
    assert row["market_value"] == pytest.approx(30.0)
    assert row["portfolio_weight"] == pytest.approx(0.3)
    assert any("duplicate" in warning.lower() for warning in result.warnings)


def test_conflicting_sector_becomes_null() -> None:
    raw = pl.DataFrame(
        {
            "snapshot_date": ["2024-06-30", "2024-06-30"],
            "fund_id": ["FUND-1", "FUND-1"],
            "security_name": ["Alpha", "Alpha"],
            "cusip": ["ALPH00010", "ALPH00010"],
            "sector": ["Technology", "Health Care"],
            "portfolio_weight": [0.1, 0.2],
            "source": ["unit", "unit"],
        }
    )
    result = normalize_holdings(raw)
    assert result.frame.get_column("sector").to_list() == [None]
    assert any("sector" in warning for warning in result.warnings)


def test_ticker_alone_is_not_a_fund_id() -> None:
    raw = _raw().drop("fund_id")
    with pytest.raises(EtfGenomeError, match="fund_id"):
        normalize_holdings(raw)


def test_fund_id_can_be_derived_from_cik_and_series() -> None:
    raw = (
        _raw()
        .drop("fund_id")
        .with_columns(
            pl.lit("1999999").alias("cik"),
            pl.lit("s000099999").alias("series_id"),
        )
    )
    result = normalize_holdings(raw)
    assert result.frame.get_column("fund_id").to_list() == ["cik:0001999999|series:S000099999"]


def test_weights_are_derived_only_when_the_snapshot_has_complete_market_values() -> None:
    raw = pl.DataFrame(
        {
            "snapshot_date": ["2024-06-30", "2024-06-30"],
            "fund_id": ["FUND-1", "FUND-1"],
            "security_name": ["Alpha", "Beta"],
            "cusip": ["ALPH00010", "BETA00010"],
            "market_value": [25.0, 75.0],
            "source": ["unit", "unit"],
        }
    )
    result = normalize_holdings(raw)
    weights = sorted(result.frame.get_column("portfolio_weight").to_list())
    assert weights == pytest.approx([0.25, 0.75])
    assert any("Derived portfolio_weight" in warning for warning in result.warnings)


def test_partial_weights_are_not_filled_in() -> None:
    raw = pl.DataFrame(
        {
            "snapshot_date": ["2024-06-30", "2024-06-30"],
            "fund_id": ["FUND-1", "FUND-1"],
            "security_name": ["Alpha", "Beta"],
            "cusip": ["ALPH00010", "BETA00010"],
            "market_value": [25.0, 75.0],
            "portfolio_weight": [0.2, None],
            "source": ["unit", "unit"],
        }
    )
    result = normalize_holdings(raw)
    assert None in result.frame.get_column("portfolio_weight").to_list()
    assert not any("Derived portfolio_weight" in warning for warning in result.warnings)


def test_alias_and_market_value_scale() -> None:
    raw = pl.DataFrame(
        {
            "report_date": ["2024-06-30"],
            "fund_id": ["FUND-1"],
            "name_of_issuer": ["Alpha"],
            "cusip": ["ALPH00010"],
            "pct_val": [5.0],
            "market_value_usd": [1.25],
            "source": ["unit"],
        }
    )
    result = normalize_holdings(raw, weight_unit="percent", market_value_scale=1000)
    row = result.frame.row(0, named=True)
    assert row["portfolio_weight"] == pytest.approx(0.05)
    assert row["market_value"] == pytest.approx(1250.0)
    assert row["security_name"] == "Alpha"


def test_nport_like_values_are_scaled_and_missing_fields_stay_null() -> None:
    raw = frame_from_nport_like(
        [
            {
                "periodOfReport": "2024-09-30",
                "cik": "0001999999",
                "seriesId": "S000099999",
                "nameOfIssuer": "Example Issuer",
                "cusip": "123456789",
                "pctVal": 2.5,
                "value": 1.5,
                "balance": 10,
                "assetCat": "EC",
                "invCountry": "US",
            }
        ]
    )
    result = normalize_holdings(raw)
    row = result.frame.row(0, named=True)
    assert row["market_value"] == pytest.approx(1500.0)
    assert row["portfolio_weight"] == pytest.approx(0.025)
    assert row["quantity"] == pytest.approx(10.0)
    assert row["isin"] is None
    assert row["sector"] is None
    assert row["country"] == "US"
    assert row["fund_id"] == "cik:0001999999|series:S000099999"


def test_non_numeric_weight_is_an_error() -> None:
    raw = _raw(portfolio_weight="not-a-number")
    with pytest.raises(EtfGenomeError, match="portfolio_weight"):
        normalize_holdings(raw)
