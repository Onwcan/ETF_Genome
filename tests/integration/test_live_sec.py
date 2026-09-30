"""Opt-in live check. Normal pytest does not run this module's test."""

from __future__ import annotations

import os

import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.services.runtime import build_update_coordinator


@pytest.mark.skipif(
    os.environ.get("ETF_GENOME_RUN_LIVE_SEC_TESTS") != "1",
    reason="Set ETF_GENOME_RUN_LIVE_SEC_TESTS=1 to contact the SEC",
)
def test_live_qqq_sync_discovers_nport_filings() -> None:
    settings = AppSettings()
    if not settings.sec_user_agent_is_configured():
        pytest.skip("ETF_GENOME_SEC_USER_AGENT is not a declared contact")
    coordinator = build_update_coordinator(settings)
    try:
        outcome = coordinator.sync_sec("manual")
    finally:
        coordinator.close()
    assert outcome.error_class is None
    assert outcome.filings_discovered >= 2
    assert outcome.filings_ingested + outcome.filings_skipped >= 1
