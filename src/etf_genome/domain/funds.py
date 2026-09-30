"""The first real fund tracked by Phase 2.

Identity is the CIK plus series id. The ticker is a display label.
"""

from __future__ import annotations

from dataclasses import dataclass

from etf_genome.domain.identifiers import build_fund_id


@dataclass(frozen=True)
class TrackedFund:
    """A fund the local application knows how to synchronize."""

    fund_id: str
    ticker: str
    name: str
    cik: str
    series_id: str
    class_id: str


QQQ = TrackedFund(
    fund_id=build_fund_id(fund_id=None, cik="0001067839", series_id="S000101292"),
    ticker="QQQ",
    name="Invesco QQQ Trust, Series 1",
    cik="0001067839",
    series_id="S000101292",
    class_id="C000271435",
)
