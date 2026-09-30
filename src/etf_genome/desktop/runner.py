"""Launch the desktop shell from cached holdings, then refresh in the background."""

from __future__ import annotations

import os
import sys
from dataclasses import replace

from etf_genome.config.settings import AppSettings
from etf_genome.desktop.summary import summary_from_view
from etf_genome.errors import EtfGenomeError
from etf_genome.logging_config import configure_logging
from etf_genome.services.fund_view import build_fund_view
from etf_genome.services.risk_inference import estimate_qqq_risk, format_risk_estimate
from etf_genome.services.runtime import build_update_coordinator


def main() -> int:
    """Open the window with local data before any network call."""

    settings = AppSettings()
    logger = configure_logging(settings)
    try:
        summary = summary_from_view(build_fund_view(settings))
        summary = replace(summary, risk_text=format_risk_estimate(estimate_qqq_risk(settings)))
        coordinator = build_update_coordinator(settings)
    except EtfGenomeError as exc:
        logger.error("%s", exc)
        print(f"ETF Genome error: {exc}", file=sys.stderr)
        return 1

    if os.environ.get("ETF_GENOME_HEADLESS_SUMMARY") == "1" and (
        os.environ.get("ETF_GENOME_DESKTOP_SMOKE") != "1"
    ):
        print(summary.as_text())
        return 0

    from etf_genome.desktop.window import run_window

    smoke = os.environ.get("ETF_GENOME_DESKTOP_SMOKE") == "1"
    quit_after_sync = os.environ.get("ETF_GENOME_DESKTOP_SYNC_ONCE") == "1"
    return run_window(
        summary,
        coordinator,
        settings,
        smoke=smoke,
        quit_after_sync=quit_after_sync and not smoke,
    )
