"""Print completed, failed, and best Optuna trials for one study name."""

from __future__ import annotations

import json
import sys

import optuna

from etf_genome.config.paths import project_root
from etf_genome.config.settings import AppSettings
from etf_genome.experiments.study import (
    best_complete_trial,
    study_name,
    study_storage,
    trial_counts,
)
from etf_genome.experiments.workflow import load_dataset


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/inspect_study.py <study_name>", file=sys.stderr)
        return 1
    _frame, meta = load_dataset(AppSettings())
    name = study_name(sys.argv[1], str(meta["fingerprint"]))
    study = optuna.load_study(study_name=name, storage=study_storage(project_root()))
    best = best_complete_trial(study)
    print(
        json.dumps(
            {
                "study": study.study_name,
                "counts": trial_counts(study),
                "best_value": best.value,
                "best_params": best.params,
                "dataset_fingerprint": study.user_attrs.get("dataset_fingerprint"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
