"""Map a narrow subset of N-PORT-like holding records into raw rows.

The official N-PORT ``value`` amount is reported in thousands of US dollars.
This adapter scales that field to dollars and converts ``pctVal`` from a
percent to a fraction. Fields the record does not contain stay null.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from etf_genome.errors import EtfGenomeError


class NportMappingError(EtfGenomeError):
    """Raised when an N-PORT-like record is not a mapping."""


def frame_from_nport_like(
    rows: list[dict[str, Any]],
    *,
    value_in_thousands: bool = True,
) -> pl.DataFrame:
    """Convert N-PORT-like dictionaries to a frame ``normalize_holdings`` accepts.

    ``portfolio_weight`` in the result is a fraction. Pass the result to
    ``normalize_holdings`` with ``weight_unit="fraction"`` and
    ``market_value_scale=1``.
    """

    scale = 1000.0 if value_in_thousands else 1.0
    mapped: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise NportMappingError("Each N-PORT-like record must be a dictionary")
        market_value = row.get("market_value")
        if market_value is None and row.get("value") is not None:
            market_value = float(row["value"]) * scale
        weight = row.get("portfolio_weight")
        if weight is None and row.get("pctVal") is not None:
            weight = float(row["pctVal"]) / 100.0
        mapped.append(
            {
                "snapshot_date": row.get("periodOfReport", row.get("snapshot_date")),
                "fund_id": row.get("fund_id"),
                "fund_name": row.get("seriesName", row.get("fund_name")),
                "ticker": row.get("fund_ticker", row.get("ticker")),
                "cik": row.get("cik"),
                "series_id": row.get("seriesId", row.get("series_id")),
                "class_id": row.get("classId", row.get("class_id")),
                "security_name": row.get("nameOfIssuer", row.get("security_name")),
                "security_ticker": row.get("security_ticker"),
                "cusip": row.get("cusip"),
                "isin": row.get("isin"),
                "asset_type": row.get("assetCat", row.get("asset_type")),
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "country": row.get("invCountry", row.get("country")),
                "quantity": row.get("balance", row.get("quantity")),
                "market_value": market_value,
                "portfolio_weight": weight,
                "currency": row.get("curCd", row.get("currency")),
                "source": row.get("source", "nport"),
                "source_timestamp": row.get("source_timestamp"),
            }
        )
    if not mapped:
        raise NportMappingError("N-PORT-like input contained no records")
    return pl.DataFrame(mapped)
