"""Compare two canonical holdings snapshots.

``overall_drift`` is the holdings-level distribution distance. A larger value
means the weight composition changed more. It does not mean the ETF became
better or worse.
"""

from __future__ import annotations

from datetime import date, datetime

import polars as pl

from etf_genome.domain.constants import UNCLASSIFIED
from etf_genome.domain.models import (
    ConcentrationDrift,
    DistributionDrift,
    DriftMetrics,
    DriftReport,
    WeightChange,
)
from etf_genome.features.concentration.metrics import compute_concentration
from etf_genome.features.drift.alignment import align_weight_vectors
from etf_genome.features.drift.distances import choose_distribution_distance
from etf_genome.features.errors import CalculationError
from etf_genome.features.snapshot import require_single_snapshot


def compute_drift(
    earlier: pl.DataFrame,
    later: pl.DataFrame,
    *,
    change_limit: int = 5,
) -> DriftReport:
    """Compare ``earlier`` with a later snapshot of the same fund."""

    if change_limit < 1:
        raise ValueError("change_limit must be at least 1")
    earlier_snapshot = require_single_snapshot(earlier)
    later_snapshot = require_single_snapshot(later)
    earlier_fund = _only_text(earlier_snapshot, "fund_id")
    later_fund = _only_text(later_snapshot, "fund_id")
    if earlier_fund != later_fund:
        raise CalculationError(f"Cannot compare different funds ({earlier_fund} and {later_fund})")
    from_date = _only_date(earlier_snapshot, "snapshot_date")
    to_date = _only_date(later_snapshot, "snapshot_date")
    if from_date >= to_date:
        raise CalculationError("The first snapshot must be strictly earlier than the second")

    notes: list[str] = []
    holdings_drift, holding_notes = _distribution_drift(
        _security_weights(earlier_snapshot),
        _security_weights(later_snapshot),
    )
    earlier_sectors, earlier_sector_notes = _label_weights(earlier_snapshot, "sector")
    later_sectors, later_sector_notes = _label_weights(later_snapshot, "sector")
    if _only_unclassified(earlier_sectors) and _only_unclassified(later_sectors):
        sector_drift = DistributionDrift(
            metric="unavailable",
            value=None,
            notes=[
                "Sector classifications were not provided by the source. "
                "Sector drift was not calculated."
            ],
        )
        sector_notes = [*earlier_sector_notes, *later_sector_notes, *sector_drift.notes]
    else:
        sector_drift, sector_notes = _distribution_drift(
            (earlier_sectors, earlier_sector_notes),
            (later_sectors, later_sector_notes),
        )
    notes.extend(holding_notes)
    notes.extend(sector_notes)

    earlier_concentration = compute_concentration(earlier_snapshot)
    later_concentration = compute_concentration(later_snapshot)
    top_10_delta = _subtract(
        later_concentration.top_10_weight,
        earlier_concentration.top_10_weight,
    )
    hhi_delta = _subtract(later_concentration.hhi, earlier_concentration.hhi)
    holdings_count_delta = later_concentration.holdings_count - earlier_concentration.holdings_count
    concentration = ConcentrationDrift(
        top_10_delta=top_10_delta,
        hhi_delta=hhi_delta,
        holdings_count_delta=holdings_count_delta,
    )
    increases, decreases, change_notes = _weight_changes(
        earlier_snapshot,
        later_snapshot,
        limit=change_limit,
    )
    notes.extend(change_notes)
    metrics = DriftMetrics(
        holdings_distance=holdings_drift.value,
        holdings_distance_metric=holdings_drift.metric,
        sector_distance=sector_drift.value,
        sector_distance_metric=sector_drift.metric,
        top_10_delta=top_10_delta,
        hhi_delta=hhi_delta,
        holdings_count_delta=holdings_count_delta,
    )
    return DriftReport(
        from_date=from_date,
        to_date=to_date,
        overall_drift=holdings_drift.value,
        overall_drift_metric=holdings_drift.metric,
        holdings_drift=holdings_drift,
        sector_drift=sector_drift,
        concentration_drift=concentration,
        metrics=metrics,
        largest_weight_increases=increases,
        largest_weight_decreases=decreases,
        notes=notes,
    )


def _only_unclassified(weights: dict[str, float]) -> bool:
    classified = [label for label in weights if label != UNCLASSIFIED]
    return not classified


def _distribution_drift(
    earlier: tuple[dict[str, float], list[str]],
    later: tuple[dict[str, float], list[str]],
) -> tuple[DistributionDrift, list[str]]:
    earlier_weights, earlier_notes = earlier
    later_weights, later_notes = later
    _keys, left, right = align_weight_vectors(earlier_weights, later_weights)
    value, metric, metric_notes = choose_distribution_distance(left, right)
    notes = [*earlier_notes, *later_notes, *metric_notes]
    return DistributionDrift(metric=metric, value=value, notes=notes), notes


def _security_weights(frame: pl.DataFrame) -> tuple[dict[str, float], list[str]]:
    weights: dict[str, float] = {}
    notes: list[str] = []
    for row in frame.select(["security_id", "portfolio_weight"]).iter_rows(named=True):
        weight = row["portfolio_weight"]
        security_id = str(row["security_id"])
        if weight is None:
            notes.append(
                f"{security_id} was omitted from the holdings distribution because "
                "portfolio_weight is null"
            )
            continue
        weights[security_id] = float(weight)
    return weights, notes


def _label_weights(frame: pl.DataFrame, column: str) -> tuple[dict[str, float], list[str]]:
    if column not in frame.columns:
        return {UNCLASSIFIED: 0.0}, [f"{column} is missing; sector or country drift is empty"]
    labeled = frame.with_columns(pl.col(column).fill_null(UNCLASSIFIED).alias("_label"))
    grouped = labeled.group_by("_label").agg(
        pl.when(pl.col("portfolio_weight").is_not_null().any())
        .then(pl.col("portfolio_weight").sum())
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("weight")
    )
    weights: dict[str, float] = {}
    notes: list[str] = []
    for label, weight in grouped.iter_rows():
        if weight is None:
            notes.append(f"{column} {label} was omitted because its weights are null")
            continue
        weights[str(label)] = float(weight)
    return weights, notes


def _weight_changes(
    earlier: pl.DataFrame,
    later: pl.DataFrame,
    *,
    limit: int,
) -> tuple[list[WeightChange], list[WeightChange], list[str]]:
    earlier_rows = _change_rows(earlier)
    later_rows = _change_rows(later)
    notes: list[str] = []
    changes: list[WeightChange] = []
    for security_id in sorted(set(earlier_rows) | set(later_rows)):
        left = earlier_rows.get(security_id)
        right = later_rows.get(security_id)
        left_weight = None if left is None else left[1]
        right_weight = None if right is None else right[1]
        if (left is not None and left_weight is None) or (
            right is not None and right_weight is None
        ):
            notes.append(
                f"{security_id} was omitted from weight-change ranks because a snapshot "
                "reports the holding without a portfolio_weight"
            )
            continue
        from_weight = 0.0 if left is None or left_weight is None else left_weight
        to_weight = 0.0 if right is None or right_weight is None else right_weight
        name = None
        if right is not None and right[0] is not None:
            name = right[0]
        elif left is not None:
            name = left[0]
        changes.append(
            WeightChange(
                security_id=security_id,
                security_name=name,
                from_weight=from_weight,
                to_weight=to_weight,
                delta=to_weight - from_weight,
            )
        )
    increases = [change for change in changes if change.delta > 0]
    decreases = [change for change in changes if change.delta < 0]
    increases.sort(key=lambda change: (-change.delta, change.security_id))
    decreases.sort(key=lambda change: (change.delta, change.security_id))
    return increases[:limit], decreases[:limit], notes


def _change_rows(frame: pl.DataFrame) -> dict[str, tuple[str | None, float | None]]:
    rows: dict[str, tuple[str | None, float | None]] = {}
    for row in frame.select(["security_id", "security_name", "portfolio_weight"]).iter_rows(
        named=True
    ):
        weight = row["portfolio_weight"]
        rows[str(row["security_id"])] = (
            None if row["security_name"] is None else str(row["security_name"]),
            None if weight is None else float(weight),
        )
    return rows


def _only_value(frame: pl.DataFrame, column: str) -> object:
    values = frame.get_column(column).unique().to_list()
    if len(values) != 1:
        raise CalculationError(f"Expected one {column} value in the snapshot")
    return values[0]


def _only_text(frame: pl.DataFrame, column: str) -> str:
    value = _only_value(frame, column)
    if not isinstance(value, str):
        raise CalculationError(f"Expected a text value for {column}")
    return value


def _only_date(frame: pl.DataFrame, column: str) -> date:
    value = _only_value(frame, column)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise CalculationError(f"Expected a date value for {column}")


def _subtract(later: float | None, earlier: float | None) -> float | None:
    if later is None or earlier is None:
        return None
    return later - earlier
