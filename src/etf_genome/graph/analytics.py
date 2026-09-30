"""Deterministic holdings-graph metrics. These are not return forecasts."""

from __future__ import annotations

import math

import numpy as np
import polars as pl


def portfolio_vectors(edges: pl.DataFrame) -> tuple[list[str], list[str], np.ndarray]:
    """Align portfolio weights on canonical security ids. Missing weights stay zero."""

    if edges.is_empty():
        return [], [], np.zeros((0, 0))
    funds = edges.get_column("etf_node_id").unique().sort().to_list()
    securities = edges.get_column("security_node_id").unique().sort().to_list()
    matrix = np.zeros((len(funds), len(securities)), dtype=np.float64)
    fund_index = {fund: index for index, fund in enumerate(funds)}
    security_index = {security: index for index, security in enumerate(securities)}
    for row in edges.iter_rows(named=True):
        weight = row["portfolio_weight"]
        if weight is None:
            continue
        matrix[fund_index[row["etf_node_id"]], security_index[row["security_node_id"]]] += float(
            weight
        )
    return [str(item) for item in funds], [str(item) for item in securities], matrix


def pair_metrics(edges: pl.DataFrame, *, min_shared: int = 1) -> pl.DataFrame:
    """ETF-to-ETF projection. The bipartite edge list remains authoritative."""

    funds, _securities, matrix = portfolio_vectors(edges)
    sets = _holding_sets(edges)
    rows: list[dict[str, object]] = []
    for left in range(len(funds)):
        for right in range(left + 1, len(funds)):
            shared = sets[funds[left]] & sets[funds[right]]
            union = sets[funds[left]] | sets[funds[right]]
            shared_count = len(shared)
            if shared_count < min_shared:
                continue
            left_vector = matrix[left]
            right_vector = matrix[right]
            assumptions_ok = bool(np.all(left_vector >= 0) and np.all(right_vector >= 0))
            overlap = _weighted_overlap(left_vector, right_vector)
            rows.append(
                {
                    "left_etf": funds[left],
                    "right_etf": funds[right],
                    "shared_holding_count": shared_count,
                    "jaccard": (shared_count / len(union)) if union else None,
                    "weighted_overlap": overlap,
                    "weighted_overlap_is_long_only": assumptions_ok,
                    "cosine_similarity": _cosine(left_vector, right_vector),
                }
            )
    if not rows:
        return pl.DataFrame(
            schema={
                "left_etf": pl.Utf8,
                "right_etf": pl.Utf8,
                "shared_holding_count": pl.Int64,
                "jaccard": pl.Float64,
                "weighted_overlap": pl.Float64,
                "weighted_overlap_is_long_only": pl.Boolean,
                "cosine_similarity": pl.Float64,
            }
        )
    return pl.DataFrame(rows).sort(["left_etf", "right_etf"])


def crowding(edges: pl.DataFrame, universe_etf_count: int) -> pl.DataFrame:
    """Security crowding inside this graph universe, not the entire ETF market."""

    if edges.is_empty():
        return pl.DataFrame()
    return (
        edges.group_by("security_node_id")
        .agg(
            pl.col("etf_node_id").n_unique().alias("etf_count"),
            pl.col("portfolio_weight").sum().alias("total_reported_weight"),
            pl.col("portfolio_weight").mean().alias("average_holding_weight"),
            pl.col("portfolio_weight").max().alias("maximum_holding_weight"),
            pl.col("security_ticker").drop_nulls().first(),
            pl.col("security_name").drop_nulls().first(),
        )
        .with_columns(pl.lit(universe_etf_count).alias("universe_etf_count"))
        .sort(["etf_count", "total_reported_weight"], descending=True)
    )


def etf_degree(edges: pl.DataFrame) -> pl.DataFrame:
    if edges.is_empty():
        return pl.DataFrame()
    return (
        edges.group_by("etf_node_id")
        .agg(
            pl.len().alias("holding_count"),
            pl.col("portfolio_weight").sum().alias("weight_sum"),
            pl.col("portfolio_weight").abs().sum().alias("absolute_weighted_degree"),
        )
        .sort("etf_node_id")
    )


def _holding_sets(edges: pl.DataFrame) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {}
    for row in edges.iter_rows(named=True):
        sets.setdefault(str(row["etf_node_id"]), set()).add(str(row["security_node_id"]))
    return sets


def _weighted_overlap(left: np.ndarray, right: np.ndarray) -> float:
    """Sum of per-security minimum weights.

    When every weight is non-negative this is a long-only overlap mass.
    Negative weights are not clamped. The caller records that the percentage
    interpretation does not hold in that case.
    """

    return float(np.minimum(left, right).sum())


def _cosine(left: np.ndarray, right: np.ndarray) -> float | None:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0 or right_norm == 0 or math.isnan(left_norm) or math.isnan(right_norm):
        return None
    return float(np.dot(left, right) / (left_norm * right_norm))
