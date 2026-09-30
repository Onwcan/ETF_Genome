"""Train the structural graph baseline in the isolated graph environment."""

from __future__ import annotations

import json
import sys
from datetime import date

import polars as pl

from etf_genome.config.paths import project_root
from etf_genome.config.settings import AppSettings


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/train_graph_baseline.py YYYY-MM-DD", file=sys.stderr)
        return 1
    snapshot = date.fromisoformat(sys.argv[1])
    settings = AppSettings()
    universe = json.loads(
        (settings.processed_dir / "graph" / "universe_manifest.json").read_text(encoding="utf-8")
    )
    graph_dir = (
        settings.processed_dir / "graph" / str(universe["universe_id"]) / snapshot.isoformat()
    )
    manifest = json.loads((graph_dir / "manifest.json").read_text(encoding="utf-8"))
    edges_frame = pl.read_parquet(graph_dir / "edges.parquet")
    edges = [
        (
            str(row["etf_node_id"]),
            str(row["security_node_id"]),
            float(row["portfolio_weight"]),
        )
        for row in edges_frame.iter_rows(named=True)
        if row["portfolio_weight"] is not None
    ]
    root = project_root()
    sys.path.insert(0, str(root))
    from research.graph.baseline import train_baseline

    output = root / "models" / "shock_graph" / "graph_baseline"
    metadata = train_baseline(
        edges,
        graph_fingerprint=str(manifest["graph_fingerprint"]),
        universe_fingerprint=str(universe["universe_fingerprint"]),
        snapshot_date=snapshot.isoformat(),
        output_dir=output,
    )
    print(json.dumps({"device": metadata["device"], "metrics": metadata["metrics"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
