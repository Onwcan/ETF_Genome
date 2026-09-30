"""Configuration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from etf_genome.config.paths import default_data_dir, project_root
from etf_genome.config.settings import AppSettings


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AppSettings(log_level="verbose")


def test_retry_count_is_bounded() -> None:
    with pytest.raises(ValidationError):
        AppSettings(sec_max_retries=9)


def test_data_dir_override_is_resolved(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "custom")
    assert settings.resolved_data_dir == (tmp_path / "custom").resolve()
    assert settings.sqlite_path == settings.resolved_data_dir / "catalog.sqlite"
    assert settings.duckdb_path == settings.resolved_data_dir / "analytics.duckdb"
    assert settings.holdings_dir == settings.resolved_data_dir / "processed" / "holdings"
    assert settings.log_dir == settings.resolved_data_dir / "logs"


def test_default_data_dir_stays_inside_the_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ETF_GENOME_DATA_DIR", raising=False)
    monkeypatch.setattr("etf_genome.config.paths.is_frozen", lambda: False)
    assert default_data_dir() == (project_root() / "data").resolve()


def test_frozen_data_dir_uses_local_appdata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("ETF_GENOME_DATA_DIR", raising=False)
    monkeypatch.setattr("etf_genome.config.paths.is_frozen", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_data_dir() == (tmp_path / "ETFGenome").resolve()


def test_feature_flag_can_be_set_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETF_GENOME_FEATURE_FLAGS__LIVE_SEC_FETCH", "true")
    settings = AppSettings()
    assert settings.feature_flags.live_sec_fetch is True
    assert settings.feature_flags.mandate_drift is True


def test_placeholder_sec_user_agent_is_not_treated_as_configured() -> None:
    settings = AppSettings(
        sec_user_agent="ETF Genome Phase1 (research; set ETF_GENOME_SEC_USER_AGENT)"
    )
    assert settings.sec_user_agent_is_configured() is False
    configured = AppSettings(sec_user_agent="Example Desk analyst@example.com")
    assert configured.sec_user_agent_is_configured() is True


def test_relative_data_dir_becomes_absolute() -> None:
    settings = AppSettings(data_dir=Path("relative-data"))
    assert settings.resolved_data_dir.is_absolute()
