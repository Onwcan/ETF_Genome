"""Register a trained model as a candidate. This does not promote it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from etf_genome.config.paths import project_root
from etf_genome.experiments.workflow import register_trained_model


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/register_model.py <model.metadata.json>", file=sys.stderr)
        return 1
    record = register_trained_model(project_root(), Path(sys.argv[1]))
    payload = {
        "model_id": record.model_id,
        "model_version": record.model_version,
        "state": record.state,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
