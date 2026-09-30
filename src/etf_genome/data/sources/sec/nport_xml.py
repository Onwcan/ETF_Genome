"""Parse an NPORT-P XML document into rows the holdings normalizer accepts.

The original XML remains the raw artifact. This parser does not invent sector
or industry classifications. ``pctVal`` is a percentage of net assets in the
N-PORT XML specification and is converted to a fraction. ``valUSD`` is US
dollars in that specification, not thousands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ET
import polars as pl
from defusedxml.common import DefusedXmlException

from etf_genome.errors import EtfGenomeError

PARSER_VERSION = "nport-xml-4"
_PLACEHOLDERS = frozenset({"N/A", "NA", "NONE", "NULL", "NOT AVAILABLE", "NOT APPLICABLE"})


class NportXmlError(EtfGenomeError):
    """Raised when an N-PORT document cannot be parsed into holdings."""


@dataclass(frozen=True)
class ParsedNport:
    """Source fields extracted from one NPORT-P document."""

    report_date: date
    cik: str | None
    series_id: str | None
    class_id: str | None
    fund_name: str | None
    rows: list[dict[str, object]]
    warnings: list[str] = field(default_factory=list)

    def raw_frame(self) -> pl.DataFrame:
        if not self.rows:
            raise NportXmlError("N-PORT document did not contain any holdings")
        # Explicit strings. A later alphanumeric CUSIP must not be rejected
        # because early rows looked numeric.
        return pl.DataFrame(
            self.rows,
            schema={
                "snapshot_date": pl.Utf8,
                "security_name": pl.Utf8,
                "security_ticker": pl.Utf8,
                "cusip": pl.Utf8,
                "isin": pl.Utf8,
                "asset_type": pl.Utf8,
                "country": pl.Utf8,
                "quantity": pl.Float64,
                "market_value": pl.Float64,
                "portfolio_weight": pl.Float64,
                "currency": pl.Utf8,
                "sector": pl.Utf8,
                "industry": pl.Utf8,
            },
        )


def parse_nport_xml(payload: bytes, *, max_bytes: int) -> ParsedNport:
    """Parse NPORT-P XML, including documents that use a default namespace."""

    if len(payload) > max_bytes:
        raise NportXmlError("N-PORT document exceeds the configured size limit")
    if not payload.strip():
        raise NportXmlError("N-PORT document is empty")
    try:
        root = ET.fromstring(payload)
    except (ParseError, DefusedXmlException) as exc:
        raise NportXmlError("N-PORT document is not valid XML") from exc

    if _local(root.tag) not in {"edgarSubmission", "nport"}:
        raise NportXmlError("XML root is not an N-PORT submission")
    submission_type = _first_text(root, "submissionType")
    if submission_type is not None and submission_type.upper() != "NPORT-P":
        raise NportXmlError(f"XML submission type is {submission_type}, not NPORT-P")

    report_text = _first_text(root, "repPdDate")
    if report_text is None:
        raise NportXmlError("N-PORT document has no repPdDate")
    try:
        report_date = date.fromisoformat(report_text[:10])
    except ValueError as exc:
        raise NportXmlError("N-PORT repPdDate is not an ISO date") from exc

    holdings = [element for element in root.iter() if _local(element.tag) == "invstOrSec"]
    if not holdings:
        raise NportXmlError("N-PORT document has no investment records")

    warnings: list[str] = []
    rows: list[dict[str, object]] = []
    for position, holding in enumerate(holdings, start=1):
        rows.append(_holding_row(holding, report_date, position))
    return ParsedNport(
        report_date=report_date,
        cik=_first_text(root, "cik"),
        series_id=_first_text(root, "seriesId"),
        class_id=_first_text(root, "classId"),
        fund_name=_first_text(root, "regName"),
        rows=rows,
        warnings=warnings,
    )


def _holding_row(
    holding: Element,
    report_date: date,
    position: int,
) -> dict[str, object]:
    name = _real(_direct_text(holding, "name"))
    if name is None:
        name = _real(_direct_text(holding, "title"))
    cusip = _real(_direct_text(holding, "cusip"))
    isin = _real(_identifier_text(holding, "isin"))
    ticker = _real(_identifier_text(holding, "ticker"))
    if name is None and cusip is None and isin is None and ticker is None:
        raise NportXmlError(f"Investment {position} has no name, CUSIP, or ISIN")
    return {
        "snapshot_date": report_date.isoformat(),
        "security_name": name,
        "security_ticker": ticker,
        "cusip": cusip,
        "isin": isin,
        "asset_type": _direct_text(holding, "assetCat"),
        "country": _direct_text(holding, "invCountry"),
        "quantity": _optional_float(holding, "balance"),
        "market_value": _optional_float(holding, "valUSD"),
        "portfolio_weight": _percent_to_fraction(holding, "pctVal"),
        "currency": _direct_text(holding, "curCd"),
        "sector": None,
        "industry": None,
    }


def _percent_to_fraction(element: Element, name: str) -> float | None:
    value = _optional_float(element, name)
    if value is None:
        return None
    return value / 100.0


def _optional_float(element: Element, name: str) -> float | None:
    text = _direct_text(element, name)
    if text is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError as exc:
        raise NportXmlError(f"N-PORT field {name} is not numeric") from exc


def _real(value: str | None) -> str | None:
    """Treat reported placeholders as missing. They are not identifiers."""

    if value is None:
        return None
    if value.strip().upper() in _PLACEHOLDERS:
        return None
    return value


def _direct_text(element: Element, name: str) -> str | None:
    """Read a direct child only, so nested derivative underlyings are not the position."""

    for child in list(element):
        if _local(child.tag) != name:
            continue
        text = (child.text or "").strip() or child.attrib.get("value", "").strip()
        if text:
            return text
    return None


def _identifier_text(holding: Element, name: str) -> str | None:
    direct = _direct_text(holding, name)
    if direct is not None:
        return direct
    for child in list(holding):
        if _local(child.tag) == "identifiers":
            return _first_text(child, name)
    return None


def _first_text(element: Element, name: str) -> str | None:
    for child in element.iter():
        if child is element or _local(child.tag) != name:
            continue
        text = (child.text or "").strip() or child.attrib.get("value", "").strip()
        if text:
            return text
    return None


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag
