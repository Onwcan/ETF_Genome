"""Canonical ETF and security identities for the shock graph."""

from __future__ import annotations

from etf_genome.domain.identifiers import IdentifierError, build_fund_id, build_security_id

_PLACEHOLDERS = {"N/A", "NA", "NONE", "NULL", "NAN", "-", "--", "UNKNOWN"}
SCHEMA_VERSION = "shock-graph-1"


def clean_identifier(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text or text in _PLACEHOLDERS:
        return None
    return text


def etf_node_id(*, cik: str, series_id: str) -> str:
    return build_fund_id(fund_id=None, cik=cik, series_id=series_id)


def security_node_id(
    *,
    cusip: object,
    isin: object,
    ticker: object,
    security_name: object,
) -> str:
    try:
        return build_security_id(
            cusip=clean_identifier(cusip),
            isin=clean_identifier(isin),
            ticker=clean_identifier(ticker),
            security_name=None if clean_identifier(security_name) is None else str(security_name),
        )
    except IdentifierError as exc:
        raise IdentifierError("holding has no usable cusip, isin, ticker, or name") from exc
