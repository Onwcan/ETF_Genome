"""Refit one frozen Optuna trial and score the untouched test split."""

from __future__ import annotations

import json
import sys

from etf_genome.config.settings import AppSettings
from etf_genome.experiments.workflow import config_from_path, train_best
from etf_genome.logging_config import configure_logging


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/train_best_risk_model.py <study_name>", file=sys.stderr)
        return 1
    settings = AppSettings()
    configure_logging(settings)
    metadata = train_best(settings, config_from_path(), sys.argv[1])
    print(
        json.dumps(
            {
                "model_id": metadata["model_id"],
                "model_version": metadata["model_version"],
                "metrics": metadata["metrics"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
