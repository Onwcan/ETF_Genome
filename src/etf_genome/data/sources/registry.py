"""Market-data provider registry.

Training stays on the Twelve Data file. Other providers can be constructed
for comparison. A missing key does not raise; the provider reports
``NOT_CONFIGURED``. Stooq is catalogued and not constructed.
"""

from __future__ import annotations

from dataclasses import dataclass

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.alpha_vantage import AlphaVantageProvider
from etf_genome.data.sources.capabilities import CATALOG, ProviderCapabilities
from etf_genome.data.sources.market import PROVIDER_TWELVE_DATA, MarketDataProvider
from etf_genome.data.sources.massive import MassiveProvider
from etf_genome.data.sources.tiingo import TiingoProvider
from etf_genome.data.sources.twelve_data import TwelveDataProvider
from etf_genome.data.sources.yahoo import YahooFinanceProvider

AUTHORITATIVE_PROVIDER = PROVIDER_TWELVE_DATA


@dataclass(frozen=True)
class ProviderAvailability:
    """Configuration and capability snapshot. Health comes from real syncs."""

    name: str
    classification: str
    configured: bool
    requires_api_key: bool
    suitable_for_training: bool
    official_api: bool
    notes: str


def health_from_status(status: str) -> str:
    """Map a sync or fetch status onto a small health label."""

    labels = {
        "ok": "AVAILABLE",
        "current": "AVAILABLE",
        "NOT_CONFIGURED": "NOT_CONFIGURED",
        "not_configured": "NOT_CONFIGURED",
        "rate_limit": "RATE_LIMITED",
        "offline": "OFFLINE",
        "timeout": "OFFLINE",
    }
    return labels.get(status, "ERROR")


class MarketDataProviderRegistry:
    """Create configured providers without inventing credentials."""

    def capabilities(self, name: str) -> ProviderCapabilities:
        try:
            return CATALOG[name]
        except KeyError as exc:
            raise ValueError(f"{name} is not a known market-data provider.") from exc

    def list_providers(
        self, settings: AppSettings | None = None
    ) -> tuple[ProviderAvailability, ...]:
        return tuple(self.describe(name, settings) for name in CATALOG)

    def describe(self, name: str, settings: AppSettings | None = None) -> ProviderAvailability:
        item = self.capabilities(name)
        return ProviderAvailability(
            name=item.name,
            classification=item.classification,
            configured=self.is_configured(name, settings),
            requires_api_key=item.requires_api_key,
            suitable_for_training=item.suitable_for_training,
            official_api=item.official_api,
            notes=item.notes,
        )

    def implemented(self) -> tuple[str, ...]:
        return tuple(name for name, item in CATALOG.items() if item.classification != "UNSUITABLE")

    def is_configured(self, name: str, settings: AppSettings | None) -> bool:
        item = self.capabilities(name)
        if not item.requires_api_key:
            return item.classification != "UNSUITABLE"
        if settings is None:
            return False
        keys = {
            "twelvedata": settings.twelve_data_key_value(),
            "tiingo": settings.tiingo_key_value(),
            "massive": settings.massive_key_value(),
            "alphavantage": settings.alpha_vantage_key_value(),
        }
        return bool(keys.get(name))

    def authoritative_name(self) -> str:
        """The series used for features and models. This does not fail over."""

        return AUTHORITATIVE_PROVIDER

    def create(
        self,
        name: str,
        settings: AppSettings | None = None,
        api_key: str | None = None,
    ) -> MarketDataProvider:
        """Build one provider. ``api_key`` overrides settings for tests."""

        self.capabilities(name)
        if name == "stooq":
            raise ValueError("stooq is not an enabled market-data provider.")
        key = api_key
        if key is None and settings is not None:
            key = {
                "twelvedata": settings.twelve_data_key_value(),
                "tiingo": settings.tiingo_key_value(),
                "massive": settings.massive_key_value(),
                "alphavantage": settings.alpha_vantage_key_value(),
            }.get(name)
        if name == "twelvedata":
            return TwelveDataProvider(key)
        if name == "tiingo":
            return TiingoProvider(key)
        if name == "massive":
            return MassiveProvider(key)
        if name == "alphavantage":
            return AlphaVantageProvider(key)
        if name == "yahoo":
            return YahooFinanceProvider()
        raise ValueError(f"{name} is not an implemented market-data provider.")
