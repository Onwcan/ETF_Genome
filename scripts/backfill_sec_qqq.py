"""Backfill discovered QQQ NPORT-P filings. Does not crawl other funds."""

from __future__ import annotations

import json
import sys

from etf_genome.config.settings import AppSettings
from etf_genome.errors import EtfGenomeError
from etf_genome.logging_config import configure_logging
from etf_genome.services.sec_backfill import backfill_qqq_filings


def main() -> int:
    settings = AppSettings()
    configure_logging(settings)
    if settings.offline_mode:
        print("Offline mode is on. SEC backfill was not started.", file=sys.stderr)
        return 1
    if not settings.sec_user_agent_is_configured():
        print("ETF_GENOME_SEC_USER_AGENT is not configured.", file=sys.stderr)
        return 1
    try:
        report = backfill_qqq_filings(settings)
    except EtfGenomeError:
        print("ETF Genome could not backfill SEC filings.", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    if report["failed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
