"""Domain models for funds, holdings, concentration, and drift.

Portfolio weights are fractions of the reported basis (0.25 means 25 percent),
not percents. Money amounts are IEEE-754 floats because the analytical engine
uses Polars and NumPy. That is a Phase 1 limitation, not an assertion that
float arithmetic is exact for currency.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ETF(BaseModel):
    """A fund share class or series tracked by ETF Genome."""

    fund_id: str
    name: str | None = None
    ticker: str | None = None
    cik: str | None = None
    series_id: str | None = None
    class_id: str | None = None


class FundMetadata(BaseModel):
    """Locally stored descriptive metadata for a fund."""

    fund_id: str
    name: str | None = None
    ticker: str | None = None
    cik: str | None = None
    series_id: str | None = None
    class_id: str | None = None


class Security(BaseModel):
    """A constituent identity. ``security_id`` is the internal key."""

    security_id: str
    name: str | None = None
    cusip: str | None = None
    isin: str | None = None
    ticker: str | None = None
    asset_type: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None


class Holding(BaseModel):
    """One constituent row inside a holdings snapshot."""

    security_id: str
    security_name: str | None = None
    security_ticker: str | None = None
    cusip: str | None = None
    isin: str | None = None
    asset_type: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    quantity: float | None = None
    market_value: float | None = None
    portfolio_weight: float | None = None
    currency: str | None = None


class HoldingsSnapshot(BaseModel):
    """A fund portfolio as reported on one date."""

    snapshot_date: date
    fund_id: str
    fund_name: str | None = None
    ticker: str | None = None
    cik: str | None = None
    series_id: str | None = None
    class_id: str | None = None
    holdings: list[Holding]
    source: str
    source_timestamp: datetime | None = None
    currency: str | None = None


class SectorExposure(BaseModel):
    """Summed portfolio weight for one sector label."""

    sector: str
    weight: float | None
    holding_count: int


class CountryExposure(BaseModel):
    """Summed portfolio weight for one country label."""

    country: str
    weight: float | None
    holding_count: int


class PositionWeight(BaseModel):
    """A holding ranked by portfolio weight."""

    security_id: str
    security_name: str | None = None
    portfolio_weight: float | None = None
    sector: str | None = None
    country: str | None = None


class ConcentrationMetrics(BaseModel):
    """Deterministic concentration statistics for one snapshot.

    ``top_*_weight`` values use the reported weights and are not renormalized.
    ``hhi`` is the Herfindahl-Hirschman index of the observed weight
    distribution after it is scaled to sum to 1. See
    ``etf_genome.features.concentration.metrics`` for the formulas.
    """

    holdings_count: int
    weighted_holdings_count: int
    weight_sum: float | None = None
    top_1_weight: float | None = None
    top_5_weight: float | None = None
    top_10_weight: float | None = None
    hhi: float | None = None
    hhi_method: str | None = None


class DistributionDrift(BaseModel):
    """A distance between two aligned, non-negative distributions."""

    metric: str
    value: float | None
    notes: list[str] = Field(default_factory=list)


class ConcentrationDrift(BaseModel):
    """Changes in concentration levels. Deltas are later minus earlier."""

    top_10_delta: float | None
    hhi_delta: float | None
    holdings_count_delta: int


class DriftMetrics(BaseModel):
    """Scalar mandate-drift measurements between two snapshots."""

    holdings_distance: float | None
    holdings_distance_metric: str
    sector_distance: float | None
    sector_distance_metric: str
    top_10_delta: float | None
    hhi_delta: float | None
    holdings_count_delta: int


class WeightChange(BaseModel):
    """Change in one security's portfolio weight between two snapshots."""

    security_id: str
    security_name: str | None = None
    from_weight: float
    to_weight: float
    delta: float


class DriftReport(BaseModel):
    """Comparison of two holdings snapshots.

    ``overall_drift`` is the holdings-distribution distance. It is not a
    buy/sell score and it is not a judgment that drift is good or bad.
    """

    from_date: date
    to_date: date
    overall_drift: float | None
    overall_drift_metric: str
    holdings_drift: DistributionDrift
    sector_drift: DistributionDrift
    concentration_drift: ConcentrationDrift
    metrics: DriftMetrics
    largest_weight_increases: list[WeightChange]
    largest_weight_decreases: list[WeightChange]
    notes: list[str] = Field(default_factory=list)


class GenomeSnapshotReport(BaseModel):
    """Phase 1 genome view of a single holdings snapshot."""

    fund_id: str
    fund_name: str | None
    ticker: str | None
    snapshot_date: date
    concentration: ConcentrationMetrics
    sector_exposure: list[SectorExposure]
    country_exposure: list[CountryExposure]
    largest_positions: list[PositionWeight]
