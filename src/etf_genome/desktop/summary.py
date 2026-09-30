"""View model for the Phase 1 desktop window.

The window renders this object. It does not calculate holdings, concentration,
or drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from etf_genome.domain.constants import DISCLAIMER
from etf_genome.services.fund_view import FundView
from etf_genome.services.phase1 import VerticalSliceResult
from etf_genome.sync.status import freshness_label


@dataclass(frozen=True)
class DesktopSummary:
    """Text already formatted for display."""

    title: str
    fund_label: str
    comparison_label: str
    holdings_count: int | None
    top_10_text: str
    hhi_text: str
    drift_text: str
    drift_caption: str
    disclaimer: str
    data_source: str = "n/a"
    holdings_as_of: str = "n/a"
    published: str = "n/a"
    last_checked: str = "n/a"
    sync_status: str = "n/a"
    status_message: str = ""
    risk_text: str = ""

    def as_text(self) -> str:
        holdings = "n/a" if self.holdings_count is None else str(self.holdings_count)
        lines = [
            self.fund_label,
            f"Data source: {self.data_source}",
            f"Holdings as of: {self.holdings_as_of}",
            f"Published: {self.published}",
            f"Last checked: {self.last_checked}",
            f"Sync status: {self.sync_status}",
            self.comparison_label,
            "",
            f"Holdings: {holdings}",
            f"Top 10 concentration: {self.top_10_text}",
            f"HHI: {self.hhi_text}",
            f"Mandate drift ({self.drift_caption}): {self.drift_text}",
        ]
        if self.risk_text:
            lines.extend(["", self.risk_text])
        if self.status_message:
            lines.extend(["", self.status_message])
        return "\n".join(lines)


def summary_from_slice(result: VerticalSliceResult) -> DesktopSummary:
    """Format the later snapshot and the drift report for the desktop shell."""

    later = result.later
    name = later.fund_name or later.fund_id
    if later.ticker:
        name = f"{name} ({later.ticker})"
    caption = _metric_caption(result.drift.overall_drift_metric)
    return DesktopSummary(
        title="ETF Genome",
        fund_label=f"Selected ETF: {name}",
        comparison_label=(
            f"Snapshots: {result.drift.from_date.isoformat()} to {result.drift.to_date.isoformat()}"
        ),
        holdings_count=later.concentration.holdings_count,
        top_10_text=_percent(later.concentration.top_10_weight),
        hhi_text=_decimal(later.concentration.hhi),
        drift_text=_decimal(result.drift.overall_drift),
        drift_caption=caption,
        disclaimer=DISCLAIMER,
        data_source="Synthetic fixture",
        holdings_as_of=later.snapshot_date.isoformat(),
        published="n/a",
        last_checked="n/a",
        sync_status="n/a",
    )


def summary_from_view(view: FundView) -> DesktopSummary:
    """Format a cached fund view. No holdings math happens here."""

    name = f"{view.fund_name} ({view.ticker})" if view.ticker else view.fund_name
    if view.from_date is not None and view.to_date is not None:
        comparison = f"Snapshots: {view.from_date.isoformat()} to {view.to_date.isoformat()}"
    elif view.holdings_as_of is not None:
        comparison = f"Snapshots: {view.holdings_as_of.isoformat()}"
    else:
        comparison = "Snapshots: n/a"
    return DesktopSummary(
        title="ETF Genome",
        fund_label=f"ETF: {name}",
        comparison_label=comparison,
        holdings_count=view.holdings_count,
        top_10_text=_percent(view.top_10_weight),
        hhi_text=_decimal(view.hhi),
        drift_text=_decimal(view.drift_value),
        drift_caption=_metric_caption(view.drift_metric),
        disclaimer=DISCLAIMER,
        data_source=view.data_source,
        holdings_as_of=view.holdings_as_of.isoformat() if view.holdings_as_of else "n/a",
        published=view.published_at or "n/a",
        last_checked=_display_time(view.last_checked_at),
        sync_status=freshness_label(view.freshness),
        status_message=view.status_message,
    )


def _metric_caption(metric: str) -> str:
    labels = {
        "jensen_shannon_distance": "Jensen-Shannon distance",
        "cosine_distance": "cosine distance",
    }
    return labels.get(metric, metric)


def _percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _decimal(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def _display_time(value: str | None) -> str:
    if value is None:
        return "n/a"
    return value.replace("T", " ")[:16]
