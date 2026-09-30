"""Run a direct holdings shock. This does not learn secondary propagation."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.graph.shock import run_shock
from etf_genome.logging_config import configure_logging


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: python scripts/run_shock_scenario.py YYYY-MM-DD scenario.json",
            file=sys.stderr,
        )
        return 1
    settings = AppSettings()
    configure_logging(settings)
    snapshot = date.fromisoformat(sys.argv[1])
    scenario = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    shocks = {str(key): float(value) for key, value in scenario["shocks"].items()}
    universe = json.loads(
        (settings.processed_dir / "graph" / "universe_manifest.json").read_text(encoding="utf-8")
    )
    edges = pl.read_parquet(
        settings.processed_dir
        / "graph"
        / str(universe["universe_id"])
        / snapshot.isoformat()
        / "edges.parquet"
    )
    result = run_shock(
        edges,
        shocks,
        scenario_id=str(scenario.get("scenario_id", "manual")),
        snapshot_date=snapshot,
    )
    payload = {
        "scenario_id": result.scenario_id,
        "graph_snapshot_date": result.graph_snapshot_date.isoformat(),
        "assumptions": list(result.assumptions),
        "learned_secondary_propagation": "NOT IMPLEMENTED",
        "impacts": [
            {
                "etf_node_id": item.etf_node_id,
                "direct_shock": item.direct_shock,
                "covered_weight": item.covered_weight,
                "weight_sum": item.weight_sum,
                "missing_weight_count": item.missing_weight_count,
            }
            for item in result.impacts
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
