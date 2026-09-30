"""Concentration calculation tests."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from etf_genome.domain.constants import UNCLASSIFIED
from etf_genome.features.concentration.metrics import (
    compute_concentration,
    country_allocation,
    largest_positions,
    sector_allocation,
)
from etf_genome.features.errors import CalculationError


def _frame(
    weights: list[float | None],
    *,
    sectors: list[str | None] | None = None,
    countries: list[str | None] | None = None,
) -> pl.DataFrame:
    count = len(weights)
    return pl.DataFrame(
        {
            "fund_id": ["FUND-1"] * count,
            "snapshot_date": [date(2024, 6, 30)] * count,
            "security_id": [f"S{index}" for index in range(count)],
            "security_name": [f"Name {index}" for index in range(count)],
            "portfolio_weight": weights,
            "sector": sectors or ["Technology"] * count,
            "country": countries or ["US"] * count,
        }
    )


def test_equal_weights_have_known_hhi_and_top_k() -> None:
    metrics = compute_concentration(_frame([0.5, 0.5]))
    assert metrics.holdings_count == 2
    assert metrics.top_1_weight == pytest.approx(0.5)
    assert metrics.top_5_weight == pytest.approx(1.0)
    assert metrics.top_10_weight == pytest.approx(1.0)
    assert metrics.hhi == pytest.approx(0.5)
    assert metrics.hhi_method == "renormalized_observed_weights"


def test_single_holding_hhi_is_one() -> None:
    metrics = compute_concentration(_frame([1.0]))
    assert metrics.hhi == pytest.approx(1.0)
    assert metrics.top_1_weight == pytest.approx(1.0)


def test_three_equal_weights_match_one_third_hhi() -> None:
    metrics = compute_concentration(_frame([1 / 3, 1 / 3, 1 / 3]))
    assert metrics.hhi == pytest.approx(1 / 3)


def test_null_weight_is_excluded_from_concentration_but_counted_as_a_holding() -> None:
    metrics = compute_concentration(_frame([0.5, None]))
    assert metrics.holdings_count == 2
    assert metrics.weighted_holdings_count == 1
    assert metrics.top_1_weight == pytest.approx(0.5)
    assert metrics.weight_sum == pytest.approx(0.5)
    assert metrics.hhi == pytest.approx(1.0)


def test_zero_weights_do_not_invent_an_hhi() -> None:
    metrics = compute_concentration(_frame([0.0, 0.0]))
    assert metrics.holdings_count == 2
    assert metrics.top_10_weight == pytest.approx(0.0)
    assert metrics.hhi is None
    assert metrics.hhi_method is None


def test_negative_weight_uses_gross_exposure_hhi() -> None:
    metrics = compute_concentration(_frame([0.5, -0.5]))
    assert metrics.hhi == pytest.approx(0.5)
    assert metrics.hhi_method == "gross_absolute_share"
    assert metrics.top_1_weight == pytest.approx(0.5)


def test_empty_snapshot_is_rejected() -> None:
    empty = _frame([1.0]).head(0)
    with pytest.raises(CalculationError):
        compute_concentration(empty)


def test_missing_sector_is_labeled_unclassified_without_being_inferred() -> None:
    sectors = sector_allocation(_frame([0.25, 0.75], sectors=["Technology", None]))
    labels = {item.sector: item.weight for item in sectors}
    assert labels["Technology"] == pytest.approx(0.25)
    assert labels[UNCLASSIFIED] == pytest.approx(0.75)


def test_country_allocation_sums_weights() -> None:
    countries = country_allocation(_frame([0.2, 0.8], countries=["US", "TW"]))
    labels = {item.country: item.weight for item in countries}
    assert labels["TW"] == pytest.approx(0.8)
    assert labels["US"] == pytest.approx(0.2)


def test_largest_positions_are_ordered_by_weight() -> None:
    positions = largest_positions(_frame([0.1, 0.7, 0.2]), limit=2)
    assert [item.security_id for item in positions] == ["S1", "S2"]
    assert positions[0].portfolio_weight == pytest.approx(0.7)
