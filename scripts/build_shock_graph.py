"""Build one point-in-time ETF-security graph from cached N-PORT filings."""

from __future__ import annotations

import json
import sys
from datetime import date

import polars as pl

from etf_genome.config.paths import project_root
from etf_genome.config.settings import AppSettings
from etf_genome.graph.build import build_persisted_graph, quality_report
from etf_genome.graph.universe import ResolvedFund
from etf_genome.logging_config import configure_logging


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_shock_graph.py YYYY-MM-DD", file=sys.stderr)
        return 1
    settings = AppSettings()
    configure_logging(settings)
    manifest_path = settings.processed_dir / "graph" / "universe_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    funds = [
        ResolvedFund(
            ticker=str(item["ticker"]),
            category=str(item["category"]),
            reason="",
            cik=str(item["cik"]),
            series_id=str(item["series_id"]),
            class_id=str(item["class_id"]),
            fund_name=str(item["fund_name"]),
            status=str(item["status"]),
        )
        for item in payload["funds"]
    ]
    graph = build_persisted_graph(
        settings,
        funds,
        as_of=date.fromisoformat(sys.argv[1]),
        universe_id=str(payload["universe_id"]),
        universe_fingerprint=str(payload["universe_fingerprint"]),
    )
    artifact = settings.processed_dir / "graph" / str(payload["universe_id"]) / sys.argv[1]
    edges = pl.read_parquet(artifact / "edges.parquet")
    nodes = pl.read_parquet(artifact / "nodes.parquet")
    summary = {
        "graph_fingerprint": graph["graph_fingerprint"],
        "snapshot_date": graph["snapshot_date"],
        "etf_nodes": graph["etf_nodes"],
        "security_nodes": graph["security_nodes"],
        "edge_count": graph["edge_count"],
        "negative_edges": graph["negative_edges"],
        "missing_weight_edges": graph["missing_weight_edges"],
        "quality": quality_report(edges, nodes),
    }
    reports = project_root() / "reports" / "shock_graph"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "graph_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
