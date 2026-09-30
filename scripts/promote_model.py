"""Promote one registered candidate. Newer candidates stay candidates until this runs."""

from __future__ import annotations

import json
import sys

from etf_genome.config.paths import project_root
from etf_genome.experiments.registry import ModelRegistryService


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/promote_model.py <model_id> <model_version>", file=sys.stderr)
        return 1
    record = ModelRegistryService(project_root()).promote(sys.argv[1], sys.argv[2])
    payload = {
        "model_id": record.model_id,
        "model_version": record.model_version,
        "state": record.state,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
