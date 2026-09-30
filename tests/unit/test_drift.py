"""Alignment, distance, and mandate-drift tests."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from etf_genome.features.drift.alignment import align_weight_vectors
from etf_genome.features.drift.distances import (
    choose_distribution_distance,
    cosine_distance,
    jensen_shannon_distance,
)
from etf_genome.features.drift.engine import compute_drift
from etf_genome.features.errors import CalculationError


def _reference_jsd(left: list[float], right: list[float]) -> float:
    left_total = sum(left)
    right_total = sum(right)
    p = [value / left_total for value in left]
    q = [value / right_total for value in right]
    midpoint = [(a + b) / 2 for a, b in zip(p, q, strict=True)]

    def _kl(distribution: list[float], reference: list[float]) -> float:
        total = 0.0
        for value, other in zip(distribution, reference, strict=True):
            if value > 0:
                total += value * math.log2(value / other)
        return total

    divergence = 0.5 * _kl(p, midpoint) + 0.5 * _kl(q, midpoint)
    return math.sqrt(divergence)


def _snapshot(
    rows: list[tuple[str, str, float | None, str]],
    *,
    when: date,
    fund_id: str = "FUND-1",
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "fund_id": [fund_id] * len(rows),
            "snapshot_date": [when] * len(rows),
            "security_id": [row[0] for row in rows],
            "security_name": [row[1] for row in rows],
            "portfolio_weight": [row[2] for row in rows],
            "sector": [row[3] for row in rows],
            "country": ["US"] * len(rows),
        }
    )


def test_alignment_uses_the_union_and_sorts_keys() -> None:
    keys, earlier, later = align_weight_vectors({"b": 0.2, "a": 0.8}, {"a": 1.0})
    assert keys == ["a", "b"]
    assert earlier.tolist() == pytest.approx([0.8, 0.2])
    assert later.tolist() == pytest.approx([1.0, 0.0])


def test_jensen_shannon_matches_an_independent_reference() -> None:
    left = np.array([1.0, 0.0])
    right = np.array([0.5, 0.5])
    distance = jensen_shannon_distance(left, right)
    assert distance == pytest.approx(_reference_jsd([1.0, 0.0], [0.5, 0.5]))
    assert distance == pytest.approx(0.5579230453)


def test_identical_distributions_have_zero_distance() -> None:
    values = np.array([0.2, 0.8])
    assert jensen_shannon_distance(values, values) == pytest.approx(0.0)
    assert cosine_distance(values, values) == pytest.approx(0.0)


def test_orthogonal_vectors_have_cosine_distance_one() -> None:
    assert cosine_distance(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(1.0)


def test_negative_weights_select_cosine_distance() -> None:
    value, metric, notes = choose_distribution_distance(
        np.array([-0.2, 0.8]),
        np.array([0.1, 0.9]),
    )
    assert metric == "cosine_distance"
    assert value is not None
    assert notes


def test_zero_total_weight_makes_jensen_shannon_undefined() -> None:
    assert jensen_shannon_distance(np.array([0.0, 0.0]), np.array([0.0, 0.0])) is None


def test_changed_and_missing_holdings_are_ranked() -> None:
    earlier = _snapshot(
        [("A", "Alpha", 0.5, "Technology"), ("B", "Beta", 0.5, "Energy")],
        when=date(2024, 6, 30),
    )
    later = _snapshot(
        [("A", "Alpha", 0.1, "Technology"), ("C", "Gamma", 0.9, "Technology")],
        when=date(2025, 6, 30),
    )
    report = compute_drift(earlier, later)
    assert report.overall_drift_metric == "jensen_shannon_distance"
    assert report.overall_drift is not None
    assert report.overall_drift > 0
    assert report.largest_weight_increases[0].security_id == "C"
    assert report.largest_weight_increases[0].from_weight == pytest.approx(0.0)
    assert report.largest_weight_decreases[0].security_id == "B"
    assert report.largest_weight_decreases[0].to_weight == pytest.approx(0.0)
    assert report.concentration_drift.holdings_count_delta == 0
    assert report.sector_drift.value is not None
    assert report.sector_drift.value > 0


def test_null_weight_is_omitted_rather_than_treated_as_zero() -> None:
    earlier = _snapshot([("A", "Alpha", 1.0, "Technology")], when=date(2024, 6, 30))
    later = _snapshot(
        [("A", "Alpha", 1.0, "Technology"), ("B", "Beta", None, "Energy")],
        when=date(2025, 6, 30),
    )
    report = compute_drift(earlier, later)
    assert report.overall_drift == pytest.approx(0.0)
    assert any("B" in note and "null" in note for note in report.notes)
    assert all(change.security_id != "B" for change in report.largest_weight_increases)


def test_all_zero_weights_do_not_produce_a_fake_distance() -> None:
    earlier = _snapshot([("A", "Alpha", 0.0, "Technology")], when=date(2024, 6, 30))
    later = _snapshot([("A", "Alpha", 0.0, "Technology")], when=date(2025, 6, 30))
    report = compute_drift(earlier, later)
    assert report.overall_drift is None
    assert report.concentration_drift.hhi_delta is None
    assert report.concentration_drift.top_10_delta == pytest.approx(0.0)


def test_missing_sector_classifications_do_not_invent_a_sector_distance() -> None:
    earlier = _snapshot([("A", "Alpha", 1.0, None)], when=date(2024, 6, 30))
    later = _snapshot([("A", "Alpha", 0.4, None), ("B", "Beta", 0.6, None)], when=date(2025, 6, 30))
    report = compute_drift(earlier, later)
    assert report.sector_drift.value is None
    assert report.sector_drift.metric == "unavailable"
    assert report.overall_drift is not None


def test_drift_rejects_different_funds_and_unsorted_dates() -> None:
    earlier = _snapshot([("A", "Alpha", 1.0, "Technology")], when=date(2024, 6, 30))
    other_fund = _snapshot(
        [("A", "Alpha", 1.0, "Technology")],
        when=date(2025, 6, 30),
        fund_id="OTHER",
    )
    same_day = _snapshot([("A", "Alpha", 1.0, "Technology")], when=date(2024, 6, 30))
    with pytest.raises(CalculationError, match="different funds"):
        compute_drift(earlier, other_fund)
    with pytest.raises(CalculationError, match="earlier"):
        compute_drift(earlier, same_day)
