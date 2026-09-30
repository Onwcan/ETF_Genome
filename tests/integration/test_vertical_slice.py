"""End-to-end Phase 1 path using the synthetic fixture."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.desktop.summary import summary_from_slice
from etf_genome.services.phase1 import run_vertical_slice


def test_vertical_slice_stores_and_compares_the_sample_fund(settings: AppSettings) -> None:
    result = run_vertical_slice(settings)

    assert result.fund_id == "SAMPLE-SERIES-001"
    assert result.later.fund_name == "Sample Innovation ETF"
    assert result.later.ticker == "SMPL"
    assert result.later.snapshot_date == date(2025, 6, 30)
    assert result.earlier.snapshot_date == date(2024, 6, 30)
    assert result.later.concentration.holdings_count == 12
    assert result.earlier.concentration.holdings_count == 12
    assert result.later.concentration.top_1_weight == pytest.approx(0.24)
    assert result.later.concentration.top_5_weight == pytest.approx(0.71)
    assert result.later.concentration.top_10_weight == pytest.approx(0.94)
    assert result.earlier.concentration.top_10_weight == pytest.approx(0.92)
    assert result.later.concentration.hhi_method == "renormalized_observed_weights"
    assert result.drift.concentration_drift.top_10_delta == pytest.approx(0.02)
    assert result.drift.concentration_drift.holdings_count_delta == 0
    assert result.drift.concentration_drift.hhi_delta is not None
    assert result.drift.overall_drift_metric == "jensen_shannon_distance"
    assert result.drift.overall_drift is not None
    assert 0 < result.drift.overall_drift < 1

    later_sectors = {item.sector: item.weight for item in result.later.sector_exposure}
    earlier_sectors = {item.sector: item.weight for item in result.earlier.sector_exposure}
    assert later_sectors["Technology"] == pytest.approx(0.63)
    assert earlier_sectors["Technology"] == pytest.approx(0.47)
    later_countries = {item.country: item.weight for item in result.later.country_exposure}
    assert later_countries["TW"] == pytest.approx(0.09)
    assert result.later.largest_positions[0].security_name == "Gamma Semiconductor"
    assert result.drift.largest_weight_increases[0].security_name == "Gamma Semiconductor"
    assert result.drift.largest_weight_increases[0].delta == pytest.approx(0.12)
    assert result.drift.largest_weight_decreases[0].security_name == "Iota Machinery"
    assert result.drift.largest_weight_decreases[0].to_weight == pytest.approx(0.0)
    assert result.stored_holding_rows == 24
    assert result.analytics_engine in {"duckdb", "polars_fallback"}
    assert result.parquet_paths

    store = LocalHoldingsStore(settings)
    stored = store.read_holdings("SAMPLE-SERIES-001", date(2025, 6, 30))
    mu = stored.filter(pl.col("security_name") == "Mu Materials").row(0, named=True)
    kappa = stored.filter(pl.col("security_name") == "Kappa Electric").row(0, named=True)
    assert mu["isin"] is None
    assert kappa["industry"] is None
    assert stored.get_column("source").unique().to_list() == ["fixture"]
    weights = [float(value) for value in stored.get_column("portfolio_weight").to_list()]
    total = sum(weights)
    expected_hhi = sum((weight / total) ** 2 for weight in weights)
    assert result.later.concentration.hhi == pytest.approx(expected_hhi)

    summary = summary_from_slice(result)
    text = summary.as_text()
    assert "Selected ETF: Sample Innovation ETF (SMPL)" in text
    assert "Holdings: 12" in text
    assert "Top 10 concentration: 94.0%" in text
    assert "Jensen-Shannon distance" in text
    assert "financial advice" in summary.disclaimer
    assert "buy" not in text.lower()
    assert "sell" not in text.lower()
