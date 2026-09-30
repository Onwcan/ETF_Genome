"""Concentration statistics for one holdings snapshot.

Formulas
--------

Let the observed weights be the non-null ``portfolio_weight`` values. Weights
are fractions of the reported basis.

Top-k concentration is the sum of the k largest observed weights. Weights are
not renormalized, so a top-10 result of 0.42 means those positions are 42
percent of the reported basis. If fewer than k weights exist, the available
weights are summed. If no weights exist, the result is null.

The Herfindahl-Hirschman index is

    HHI = sum(s_i^2)

When every observed weight is non-negative, ``s_i = w_i / sum(w)``. Dividing
by the observed sum makes HHI comparable across snapshots whose reported
weights do not add to 1. It does not fill in missing holdings.

When any observed weight is negative, shares are gross exposure shares:

    s_i = |w_i| / sum(|w|)

``hhi_method`` records which definition was used. HHI is null when the
denominator is zero.
"""

from __future__ import annotations

import math

import polars as pl

from etf_genome.domain.constants import UNCLASSIFIED
from etf_genome.domain.models import (
    ConcentrationMetrics,
    CountryExposure,
    PositionWeight,
    SectorExposure,
)
from etf_genome.features.snapshot import require_single_snapshot


def compute_concentration(frame: pl.DataFrame) -> ConcentrationMetrics:
    """Calculate holdings count, top-k weights, and HHI for one snapshot."""

    snapshot = require_single_snapshot(frame)
    observed = [
        float(value)
        for value in snapshot.get_column("portfolio_weight").to_list()
        if value is not None
    ]
    if not observed:
        return ConcentrationMetrics(
            holdings_count=snapshot.height,
            weighted_holdings_count=0,
        )
    ordered = sorted(observed, reverse=True)
    hhi, method = _hhi(observed)
    return ConcentrationMetrics(
        holdings_count=snapshot.height,
        weighted_holdings_count=len(observed),
        weight_sum=float(math.fsum(observed)),
        top_1_weight=_top_k(ordered, 1),
        top_5_weight=_top_k(ordered, 5),
        top_10_weight=_top_k(ordered, 10),
        hhi=hhi,
        hhi_method=method,
    )


def sector_allocation(frame: pl.DataFrame) -> list[SectorExposure]:
    """Sum portfolio weights by sector.

    A null sector is reported as ``UNCLASSIFIED``. That label means the source
    did not provide a sector. It is not an inferred classification.
    """

    return [
        SectorExposure(sector=label, weight=weight, holding_count=count)
        for label, weight, count in _grouped(frame, "sector")
    ]


def country_allocation(frame: pl.DataFrame) -> list[CountryExposure]:
    """Sum portfolio weights by country. Null countries are ``UNCLASSIFIED``."""

    return [
        CountryExposure(country=label, weight=weight, holding_count=count)
        for label, weight, count in _grouped(frame, "country")
    ]


def largest_positions(frame: pl.DataFrame, *, limit: int = 10) -> list[PositionWeight]:
    """Return up to ``limit`` holdings, largest reported weight first."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    snapshot = require_single_snapshot(frame)
    ranked = snapshot.sort(
        ["portfolio_weight", "security_id"],
        descending=[True, False],
        nulls_last=True,
    ).head(limit)
    positions: list[PositionWeight] = []
    for row in ranked.iter_rows(named=True):
        positions.append(
            PositionWeight(
                security_id=row["security_id"],
                security_name=row.get("security_name"),
                portfolio_weight=row.get("portfolio_weight"),
                sector=row.get("sector"),
                country=row.get("country"),
            )
        )
    return positions


def _top_k(ordered_descending: list[float], k: int) -> float:
    return float(math.fsum(ordered_descending[:k]))


def _hhi(weights: list[float]) -> tuple[float | None, str | None]:
    if any(weight < 0 for weight in weights):
        basis = [abs(weight) for weight in weights]
        method = "gross_absolute_share"
    else:
        basis = list(weights)
        method = "renormalized_observed_weights"
    total = float(math.fsum(basis))
    if total == 0:
        return None, None
    return float(math.fsum((weight / total) ** 2 for weight in basis)), method


def _grouped(frame: pl.DataFrame, column: str) -> list[tuple[str, float | None, int]]:
    snapshot = require_single_snapshot(frame)
    if column not in snapshot.columns:
        labeled = snapshot.with_columns(pl.lit(UNCLASSIFIED).alias("_label"))
    else:
        labeled = snapshot.with_columns(pl.col(column).fill_null(UNCLASSIFIED).alias("_label"))
    grouped = (
        labeled.group_by("_label")
        .agg(
            [
                pl.len().alias("holding_count"),
                pl.when(pl.col("portfolio_weight").is_not_null().any())
                .then(pl.col("portfolio_weight").sum())
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias("weight"),
            ]
        )
        .sort(["weight", "_label"], descending=[True, False], nulls_last=True)
    )
    rows: list[tuple[str, float | None, int]] = []
    for label, weight, count in grouped.select(["_label", "weight", "holding_count"]).iter_rows():
        rows.append((str(label), None if weight is None else float(weight), int(count)))
    return rows
