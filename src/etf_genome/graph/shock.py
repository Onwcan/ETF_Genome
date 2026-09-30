"""Direct mechanical exposure. This is not a learned propagation model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import polars as pl


@dataclass(frozen=True)
class EtfShockImpact:
    etf_node_id: str
    direct_shock: float
    covered_weight: float
    weight_sum: float
    missing_weight_count: int


@dataclass(frozen=True)
class ShockScenarioResult:
    scenario_id: str
    graph_snapshot_date: date
    shocked_securities: dict[str, float]
    impacts: tuple[EtfShockImpact, ...]
    assumptions: tuple[str, ...]
    created_at: str


def run_shock(
    edges: pl.DataFrame,
    shocks: dict[str, float],
    *,
    scenario_id: str,
    snapshot_date: date,
) -> ShockScenarioResult:
    """Apply ``sum(weight * shock)`` to holdings named by security id or ticker.

    Negative portfolio weights are kept. They reverse the contribution of a
    negative security shock. Missing weights are excluded from both the shock
    and the covered weight.
    """

    assumptions = [
        "direct mechanical exposure only",
        "learned secondary propagation is not implemented",
        "negative weights are not clamped to zero",
        "missing weights are excluded",
        "a ticker that maps to more than one security is left unresolved",
    ]
    resolved, ambiguous = _resolve_shocks(edges, shocks)
    if ambiguous:
        assumptions.append("ambiguous tickers were excluded: " + ", ".join(sorted(ambiguous)))
    impacts: list[EtfShockImpact] = []
    if not edges.is_empty():
        for fund_id in edges.get_column("etf_node_id").unique().sort().to_list():
            subset = edges.filter(pl.col("etf_node_id") == fund_id)
            impacts.append(_impact(str(fund_id), subset, resolved))
    return ShockScenarioResult(
        scenario_id=scenario_id,
        graph_snapshot_date=snapshot_date,
        shocked_securities=resolved,
        impacts=tuple(impacts),
        assumptions=tuple(assumptions),
        created_at=datetime.now(UTC).isoformat(),
    )


def _resolve_shocks(
    edges: pl.DataFrame,
    shocks: dict[str, float],
) -> tuple[dict[str, float], set[str]]:
    resolved: dict[str, float] = {}
    ambiguous: set[str] = set()
    if edges.is_empty():
        return resolved, ambiguous
    known = set(edges.get_column("security_node_id").to_list())
    for key, shock in shocks.items():
        if key in known:
            resolved[key] = float(shock)
            continue
        matches = edges.filter(
            pl.col("security_ticker").cast(pl.Utf8).str.to_uppercase() == key.upper()
        )
        identifiers = matches.get_column("security_node_id").unique().to_list()
        if len(identifiers) == 1:
            resolved[str(identifiers[0])] = float(shock)
        elif len(identifiers) > 1:
            ambiguous.add(key.upper())
    return resolved, ambiguous


def _impact(fund_id: str, edges: pl.DataFrame, shocks: dict[str, float]) -> EtfShockImpact:
    direct = 0.0
    covered = 0.0
    weight_sum = 0.0
    missing = 0
    for row in edges.iter_rows(named=True):
        weight = row["portfolio_weight"]
        if weight is None:
            if row["security_node_id"] in shocks:
                missing += 1
            continue
        value = float(weight)
        weight_sum += value
        shock = shocks.get(str(row["security_node_id"]))
        if shock is None:
            continue
        covered += value
        direct += value * shock
    return EtfShockImpact(
        etf_node_id=fund_id,
        direct_shock=direct,
        covered_weight=covered,
        weight_sum=weight_sum,
        missing_weight_count=missing,
    )
