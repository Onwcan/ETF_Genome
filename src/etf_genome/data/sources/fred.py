"""Future FRED / ALFRED boundary.

Phase 2 does not download macroeconomic series. A later provider can implement
this protocol. The FRED API key, when a user configures one, must come from
``ETF_GENOME_FRED_API_KEY`` and must never be written into source or logs.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel


class FredObservation(BaseModel):
    """One point-in-time observation. ``vintage_date`` is when that value was published."""

    series_id: str
    observation_date: date
    vintage_date: date | None = None
    value: float | None = None


class FredProvider(Protocol):
    """Read observations that were published on or before ``as_of``."""

    def get_series(
        self,
        series_id: str,
        *,
        start: date,
        end: date,
        as_of: date,
    ) -> list[FredObservation]:
        """Return observations without using vintages published after ``as_of``."""

        ...
