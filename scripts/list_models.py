"""List locally registered models and their lifecycle state."""

from __future__ import annotations

import json

from etf_genome.config.paths import project_root
from etf_genome.experiments.registry import ModelRegistryService


def main() -> int:
    rows = [record.to_json() for record in ModelRegistryService(project_root()).list_models()]
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
