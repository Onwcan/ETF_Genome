"""Run or resume the configured Optuna studies. Does not promote a model."""

from __future__ import annotations

import json

from etf_genome.config.settings import AppSettings
from etf_genome.experiments.workflow import config_from_path, tune
from etf_genome.logging_config import configure_logging


def main() -> int:
    settings = AppSettings()
    configure_logging(settings)
    report = tune(settings, config_from_path())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
