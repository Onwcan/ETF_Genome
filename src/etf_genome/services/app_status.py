"""UI-neutral application status.

Pages may display this object later. They should not parse status out of
widget text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.registry import AUTHORITATIVE_PROVIDER, health_from_status


@dataclass(frozen=True)
class ApplicationStatus:
    sec_status: str
    market_provider: str
    market_health: str
    market_as_of: date | None
    holdings_as_of: str
    model_status: str
    offline: bool
    sync_running: bool


def build_application_status(
    settings: AppSettings,
    *,
    sec_status: str,
    market_status: str = "",
    market_as_of: date | None = None,
    holdings_as_of: str = "n/a",
    model_ready: bool = False,
    sync_running: bool = False,
) -> ApplicationStatus:
    if settings.offline_mode:
        health = "OFFLINE"
    elif not settings.twelve_data_key_value() and not market_status:
        health = "NOT_CONFIGURED"
    else:
        health = health_from_status(market_status or "ok")
    return ApplicationStatus(
        sec_status=sec_status,
        market_provider=AUTHORITATIVE_PROVIDER,
        market_health=health,
        market_as_of=market_as_of,
        holdings_as_of=holdings_as_of,
        model_status="ready" if model_ready else "unavailable",
        offline=settings.offline_mode,
        sync_running=sync_running,
    )
