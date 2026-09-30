"""Shared fixtures. Tests never call the public SEC API."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from etf_genome.config.settings import AppSettings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppSettings:
    monkeypatch.setenv("ETF_GENOME_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ETF_GENOME_SEC_USER_AGENT", "ETF Genome Tests tester@example.com")
    monkeypatch.setenv("ETF_GENOME_LOG_LEVEL", "INFO")
    monkeypatch.setenv("ETF_GENOME_FEATURE_FLAGS__LIVE_SEC_FETCH", "false")
    return AppSettings()
