"""Validated application settings.

Environment variables use the ``ETF_GENOME_`` prefix. Nested feature flags use
a double underscore, for example ``ETF_GENOME_FEATURE_FLAGS__LIVE_SEC_FETCH``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from etf_genome.config.paths import default_data_dir

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _secret_text(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    secret = value.get_secret_value().strip()
    return secret or None


class FeatureFlags(BaseModel):
    """Switches that keep unfinished or networked behavior off by default."""

    live_sec_fetch: bool = False
    genome_xray: bool = True
    mandate_drift: bool = True


class AppSettings(BaseSettings):
    """Runtime configuration for the Phase 1 library and desktop shell."""

    model_config = SettingsConfigDict(
        env_prefix="ETF_GENOME_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    data_dir: Path | None = None
    sec_user_agent: str = "ETF Genome Phase1 (research; set ETF_GENOME_SEC_USER_AGENT)"
    sec_timeout_seconds: float = 20.0
    sec_max_retries: int = 3
    sec_backoff_seconds: float = 0.5
    sec_backoff_factor: float = 2.0
    sec_backoff_cap_seconds: float = 30.0
    sec_min_interval_seconds: float = 1.0
    sec_cache_ttl_seconds: int = 86_400
    sec_requests_per_second: float = 1.0
    sec_max_response_bytes: int = 50_000_000
    sec_max_filings_per_sync: int = 2
    sec_update_interval_hours: float = 12.0
    auto_update_enabled: bool = True
    network_timeout_seconds: float = 20.0
    stale_after_hours: float = 12.0
    offline_mode: bool = False
    remote_cache_enabled: bool = True
    fred_api_key: str | None = None
    twelve_data_api_key: SecretStr | None = None
    tiingo_api_key: SecretStr | None = None
    massive_api_key: SecretStr | None = None
    alpha_vantage_api_key: SecretStr | None = None
    preferred_market_provider: str = "twelvedata"
    market_history_start: str = "2019-01-01"
    market_update_interval_hours: float = 6.0
    tail_drawdown_threshold: float = 0.08
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in _LOG_LEVELS:
            allowed = ", ".join(sorted(_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {allowed}")
        return normalized

    @field_validator("sec_timeout_seconds", "sec_backoff_seconds", "sec_backoff_cap_seconds")
    @classmethod
    def _positive_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timing settings must be greater than zero")
        return value

    @field_validator("sec_min_interval_seconds")
    @classmethod
    def _non_negative_interval(cls, value: float) -> float:
        if value < 0:
            raise ValueError("sec_min_interval_seconds cannot be negative")
        return value

    @field_validator("sec_max_retries")
    @classmethod
    def _retry_bounds(cls, value: int) -> int:
        if value < 0 or value > 8:
            raise ValueError("sec_max_retries must be between 0 and 8")
        return value

    @field_validator("sec_backoff_factor")
    @classmethod
    def _backoff_factor(cls, value: float) -> float:
        if value < 1:
            raise ValueError("sec_backoff_factor must be at least 1")
        return value

    @field_validator("sec_cache_ttl_seconds")
    @classmethod
    def _ttl_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("sec_cache_ttl_seconds cannot be negative")
        return value

    @field_validator("sec_requests_per_second")
    @classmethod
    def _sec_rate_cap(cls, value: float) -> float:
        if value <= 0 or value > 2:
            raise ValueError("sec_requests_per_second must be greater than 0 and at most 2")
        return value

    @field_validator("sec_update_interval_hours", "stale_after_hours")
    @classmethod
    def _hour_scale(cls, value: float) -> float:
        if value < 1:
            raise ValueError("SEC refresh and stale windows must be at least 1 hour")
        return value

    @field_validator("network_timeout_seconds")
    @classmethod
    def _network_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("network_timeout_seconds must be greater than zero")
        return value

    @field_validator("sec_max_response_bytes")
    @classmethod
    def _response_cap(cls, value: int) -> int:
        if value < 1_000 or value > 100_000_000:
            raise ValueError("sec_max_response_bytes must be between 1,000 and 100,000,000")
        return value

    @field_validator("fred_api_key")
    @classmethod
    def _blank_fred_key(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip()

    @field_validator(
        "twelve_data_api_key",
        "tiingo_api_key",
        "massive_api_key",
        "alpha_vantage_api_key",
        mode="before",
    )
    @classmethod
    def _blank_secret(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("preferred_market_provider")
    @classmethod
    def _preferred_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"twelvedata", "tiingo", "massive", "alphavantage", "yahoo"}
        if normalized not in allowed:
            raise ValueError("preferred_market_provider is not a known market provider")
        return normalized

    @field_validator("market_update_interval_hours")
    @classmethod
    def _market_interval(cls, value: float) -> float:
        if value < 1:
            raise ValueError("market_update_interval_hours must be at least 1")
        return value

    @field_validator("tail_drawdown_threshold")
    @classmethod
    def _tail_threshold(cls, value: float) -> float:
        if value <= 0 or value >= 1:
            raise ValueError("tail_drawdown_threshold must be between 0 and 1")
        return value

    def twelve_data_key_value(self) -> str | None:
        return _secret_text(self.twelve_data_api_key)

    def tiingo_key_value(self) -> str | None:
        return _secret_text(self.tiingo_api_key)

    def massive_key_value(self) -> str | None:
        return _secret_text(self.massive_api_key)

    def alpha_vantage_key_value(self) -> str | None:
        return _secret_text(self.alpha_vantage_api_key)

    @field_validator("sec_max_filings_per_sync")
    @classmethod
    def _filing_cap(cls, value: int) -> int:
        if value < 1 or value > 8:
            raise ValueError("sec_max_filings_per_sync must be between 1 and 8")
        return value

    @property
    def sec_sync_interval_seconds(self) -> float:
        """Slowest of the configured gap and the requests-per-second cap.

        Ordinary synchronization stays at or below 2 SEC requests per second.
        """

        from_rate = 1.0 / self.sec_requests_per_second
        return max(self.sec_min_interval_seconds, from_rate)

    @property
    def resolved_data_dir(self) -> Path:
        if self.data_dir is not None:
            return self.data_dir.expanduser().resolve()
        return default_data_dir()

    @property
    def raw_dir(self) -> Path:
        return self.resolved_data_dir / "raw"

    @property
    def interim_dir(self) -> Path:
        return self.resolved_data_dir / "interim"

    @property
    def processed_dir(self) -> Path:
        return self.resolved_data_dir / "processed"

    @property
    def cache_dir(self) -> Path:
        return self.resolved_data_dir / "cache"

    @property
    def log_dir(self) -> Path:
        return self.resolved_data_dir / "logs"

    @property
    def sqlite_path(self) -> Path:
        return self.resolved_data_dir / "catalog.sqlite"

    @property
    def duckdb_path(self) -> Path:
        return self.resolved_data_dir / "analytics.duckdb"

    @property
    def holdings_dir(self) -> Path:
        return self.processed_dir / "holdings"

    def ensure_directories(self) -> None:
        """Create the local data directories used by Phase 1."""

        for path in (
            self.raw_dir,
            self.interim_dir,
            self.processed_dir,
            self.cache_dir,
            self.log_dir,
            self.holdings_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def sec_user_agent_is_configured(self) -> bool:
        """Return True when the SEC user agent looks like a real contact string.

        SEC fair-access guidance asks clients to identify the application and a
        contact. The built-in placeholder is intentionally rejected for live calls.
        """

        agent = self.sec_user_agent.strip()
        if "set ETF_GENOME_SEC_USER_AGENT" in agent:
            return False
        return " " in agent and "@" in agent
