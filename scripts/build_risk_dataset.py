"""Build the QQQ point-in-time dataset without training a model."""

from __future__ import annotations

import json

from etf_genome.config.settings import AppSettings
from etf_genome.features.risk.dataset import write_dataset
from etf_genome.logging_config import configure_logging


def main() -> int:
    settings = AppSettings()
    configure_logging(settings)
    meta = write_dataset(settings)
    print(
        json.dumps(
            {
                "dataset_version": meta.get("dataset_version"),
                "feature_version": meta.get("feature_version"),
                "target_version": meta.get("target_version"),
                "row_count": meta.get("row_count"),
                "market_rows": meta.get("market_rows"),
                "genome_rows": meta.get("genome_rows"),
                "market_start": meta.get("market_start"),
                "market_end": meta.get("market_end"),
                "split_counts": meta.get("split_counts"),
                "fingerprint": meta.get("fingerprint"),
                "dataset_file": meta.get("dataset_file"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
