"""N-PORT XML parser tests. Documents are local and synthetic."""

from __future__ import annotations

from datetime import date

import pytest
from tests.fixtures.nport_documents import LATER_XML, nport_xml

from etf_genome.data.sources.sec.nport_xml import NportXmlError, ParsedNport, parse_nport_xml


def test_parser_ignores_the_default_namespace_and_keeps_missing_sector_null() -> None:
    parsed = parse_nport_xml(LATER_XML, max_bytes=1_000_000)
    assert parsed.report_date.isoformat() == "2025-06-30"
    assert parsed.series_id == "S000101292"
    assert parsed.cik == "0001067839"
    frame = parsed.raw_frame()
    assert frame.height == 3
    assert frame.get_column("sector").to_list() == [None, None, None]
    assert frame.get_column("portfolio_weight").to_list() == pytest.approx([0.4, 0.4, 0.2])
    assert frame.get_column("market_value").to_list() == pytest.approx(
        [4_000_000.0, 4_000_000.0, 2_000_000.0]
    )


def test_parser_accepts_xml_without_a_namespace() -> None:
    payload = nport_xml(
        report_date="2025-06-30",
        holdings=[("Only Name", "AAAAAA001", "100", "10")],
        namespace=False,
    )
    parsed = parse_nport_xml(payload, max_bytes=100_000)
    assert parsed.rows[0]["security_name"] == "Only Name"


def test_missing_report_date_is_rejected() -> None:
    payload = LATER_XML.replace(b"<repPdDate>2025-06-30</repPdDate>", b"")
    with pytest.raises(NportXmlError, match="repPdDate"):
        parse_nport_xml(payload, max_bytes=100_000)


def test_holding_without_an_identifier_is_rejected() -> None:
    payload = b"""<?xml version="1.0"?>
    <edgarSubmission><formData><genInfo><repPdDate>2025-06-30</repPdDate></genInfo>
    <invstOrSecs><invstOrSec><pctVal>1</pctVal></invstOrSec></invstOrSecs>
    </formData></edgarSubmission>"""
    with pytest.raises(NportXmlError, match="no name"):
        parse_nport_xml(payload, max_bytes=100_000)


def test_malformed_xml_is_rejected() -> None:
    with pytest.raises(NportXmlError, match="not valid XML"):
        parse_nport_xml(b"<edgarSubmission>", max_bytes=100_000)


def test_external_entities_are_rejected() -> None:
    payload = b"""<?xml version="1.0"?>
    <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///secret">]>
    <edgarSubmission>&xxe;</edgarSubmission>"""
    with pytest.raises(NportXmlError, match="not valid XML"):
        parse_nport_xml(payload, max_bytes=100_000)


def test_nested_derivative_fields_do_not_replace_the_position() -> None:
    payload = b"""<?xml version="1.0"?>
    <edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
      <headerData><submissionType>NPORT-P</submissionType></headerData>
      <formData><genInfo><repPdDate>2025-06-30</repPdDate></genInfo>
      <invstOrSecs><invstOrSec>
        <name>Position Alpha</name>
        <cusip>037833100</cusip>
        <pctVal>5</pctVal>
        <valUSD>10</valUSD>
        <identifiers><isin value="US0378331005"/></identifiers>
        <derivativeInfo>
          <name>Underlying Beta</name>
          <cusip>999999999</cusip>
          <pctVal>99</pctVal>
          <valUSD>999</valUSD>
        </derivativeInfo>
      </invstOrSec></invstOrSecs></formData>
    </edgarSubmission>"""
    row = parse_nport_xml(payload, max_bytes=100_000).rows[0]
    assert row["security_name"] == "Position Alpha"
    assert row["cusip"] == "037833100"
    assert row["isin"] == "US0378331005"
    assert row["portfolio_weight"] == pytest.approx(0.05)
    assert row["market_value"] == pytest.approx(10.0)
    assert row["sector"] is None


def test_placeholder_cusip_does_not_collapse_distinct_positions() -> None:
    payload = b"""<?xml version="1.0"?>
    <edgarSubmission>
      <formData><genInfo><repPdDate>2025-06-30</repPdDate></genInfo>
      <invstOrSecs>
        <invstOrSec>
          <name>Example Government Fund</name>
          <cusip>N/A</cusip>
          <pctVal>1</pctVal>
        </invstOrSec>
        <invstOrSec>
          <name>N/A</name>
          <title>Example Index Future</title>
          <cusip>N/A</cusip>
          <identifiers><ticker value="EXF6"/></identifiers>
          <pctVal>2</pctVal>
        </invstOrSec>
        <invstOrSec>
          <name>Example Issuer</name>
          <cusip>N/A</cusip>
          <identifiers><isin value="NL0015001FS8"/></identifiers>
          <pctVal>3</pctVal>
        </invstOrSec>
      </invstOrSecs></formData>
    </edgarSubmission>"""
    rows = parse_nport_xml(payload, max_bytes=100_000).rows
    assert rows[0]["cusip"] is None
    assert rows[0]["security_name"] == "Example Government Fund"
    assert rows[1]["security_name"] == "Example Index Future"
    assert rows[1]["security_ticker"] == "EXF6"
    assert rows[2]["isin"] == "NL0015001FS8"
    assert rows[2]["cusip"] is None


def test_oversized_document_is_rejected() -> None:
    with pytest.raises(NportXmlError, match="size"):
        parse_nport_xml(LATER_XML, max_bytes=20)


def test_alphanumeric_cusip_does_not_break_the_frame_schema() -> None:
    parsed = parse_nport_xml(LATER_XML, max_bytes=1_000_000)
    rows = list(parsed.rows)
    rows.append({**rows[0], "cusip": "FAU6", "security_ticker": "FAU6"})
    frame = ParsedNport(
        report_date=date(2025, 6, 30),
        cik=parsed.cik,
        series_id=parsed.series_id,
        class_id=parsed.class_id,
        fund_name=parsed.fund_name,
        rows=rows,
    ).raw_frame()
    assert frame.get_column("cusip").to_list()[-1] == "FAU6"
