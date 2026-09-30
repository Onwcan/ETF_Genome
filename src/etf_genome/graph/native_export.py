"""Export explicit graph snapshots for the optional standalone C++ engine."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import polars as pl

EDGE_COLUMNS = (
    "etf_node_id",
    "security_node_id",
    "security_ticker",
    "portfolio_weight",
)


def export_native_inputs(
    edges: pl.DataFrame, shocks: dict[str, float], output: Path
) -> tuple[Path, Path]:
    """Write only identifiers, tickers, signed weights, and scenario shocks.

    This boundary deliberately excludes filing metadata, local paths, settings,
    API responses, and credentials. Missing weights remain blank CSV fields.
    """
    missing = set(EDGE_COLUMNS) - set(edges.columns)
    if missing:
        raise ValueError("Graph is missing required columns: " + ", ".join(sorted(missing)))
    selected = edges.select(
        pl.col("etf_node_id").cast(pl.String),
        pl.col("security_node_id").cast(pl.String),
        pl.col("security_ticker").cast(pl.String).fill_null(""),
        pl.col("portfolio_weight").cast(pl.Float64),
    )
    for column in ("etf_node_id", "security_node_id"):
        if selected.filter(pl.col(column).is_null() | (pl.col(column).str.len_chars() == 0)).height:
            raise ValueError("Graph node identifiers must be nonempty.")
    for column in EDGE_COLUMNS[:3]:
        if selected.filter(pl.col(column).str.contains(r"[\x00-\x1f\x7f]")).height:
            raise ValueError("Graph text fields cannot contain control characters.")
    if selected.filter(
        pl.col("portfolio_weight").is_not_null() & ~pl.col("portfolio_weight").is_finite()
    ).height:
        raise ValueError("Portfolio weights must be finite or missing.")
    for key, value in shocks.items():
        if not key.strip() or any(
            ord(character) < 32 or ord(character) == 127 for character in key
        ):
            raise ValueError("Shock keys must be nonempty and contain no control characters.")
        if isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("Scenario shocks must be finite numbers.")
    output.mkdir(parents=True, exist_ok=True)
    edge_path, shock_path = output / "edges.csv", output / "shocks.csv"
    selected.write_csv(edge_path)
    pl.DataFrame(
        {"key": list(shocks), "shock": list(shocks.values())},
        schema={"key": pl.String, "shock": pl.Float64},
    ).write_csv(shock_path)
    return edge_path, shock_path


def demo_inputs() -> tuple[pl.DataFrame, dict[str, float]]:
    """Small synthetic graph, including a short position and a missing weight."""
    return (
        pl.DataFrame(
            {
                "etf_node_id": ["DEMO-A", "DEMO-A", "DEMO-B", "DEMO-B", "DEMO-B"],
                "security_node_id": [
                    "demo:alpha",
                    "demo:beta",
                    "demo:alpha",
                    "demo:beta",
                    "demo:gamma",
                ],
                "security_ticker": ["ALPHA", "BETA", "ALPHA", "BETA", "GAMMA"],
                "portfolio_weight": [0.6, 0.4, 0.2, -0.1, None],
            }
        ),
        {"ALPHA": -0.1, "demo:beta": -0.2, "demo:gamma": 0.05},
    )


def _load_scenario(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("shocks"), dict):
        raise ValueError("Scenario JSON must contain a 'shocks' object.")
    shocks: dict[str, float] = {}
    for key, value in payload["shocks"].items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Scenario shocks must be numbers, not strings or booleans.")
        shocks[str(key)] = float(value)
    return shocks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--edges", type=Path, help="An explicit graph edges.parquet snapshot")
    source.add_argument("--demo", action="store_true", help="Use synthetic data; no network calls")
    parser.add_argument("--scenario", type=Path, help="Scenario JSON containing a shocks object")
    parser.add_argument("--output", type=Path, required=True, help="Local CSV output directory")
    args = parser.parse_args()
    if args.edges is not None and args.scenario is None:
        parser.error("--edges requires --scenario")
    try:
        if args.demo:
            edges, shocks = demo_inputs()
        else:
            edges = pl.read_parquet(args.edges)
            shocks = {}
        if args.scenario is not None:
            shocks = _load_scenario(args.scenario)
        export_native_inputs(edges, shocks, args.output)
    except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
        parser.exit(1, f"Export failed: {exc}\n")
    print(f"Exported {edges.height} edges and {len(shocks)} shocks to edges.csv and shocks.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
