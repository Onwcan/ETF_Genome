"""Resolve the ETF universe and ingest the latest public N-PORT filing per series."""

from __future__ import annotations

import json

from etf_genome.config.paths import project_root
from etf_genome.config.settings import AppSettings
from etf_genome.graph.ingest import CATALOGUE_URL, download_catalogue, sync_resolved_funds
from etf_genome.graph.universe import load_universe_entries, resolve_universe, universe_manifest
from etf_genome.logging_config import configure_logging


def main() -> int:
    settings = AppSettings()
    configure_logging(settings)
    root = project_root()
    universe_id, entries = load_universe_entries(root / "configs" / "graph" / "etf_universe.toml")
    catalogue, size = download_catalogue(settings)
    funds = resolve_universe(entries, catalogue)
    manifest = universe_manifest(
        universe_id,
        funds,
        source_url=CATALOGUE_URL,
        source_bytes=size,
    )
    directory = settings.processed_dir / "graph"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "universe_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    report = sync_resolved_funds(settings, funds, filings_per_series=1)
    payload = {"universe": manifest, "sec": report}
    (directory / "sec_backfill.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if manifest["validation_status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
