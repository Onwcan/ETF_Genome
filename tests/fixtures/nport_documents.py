"""Builders for synthetic NPORT-P documents. These are not SEC downloads."""

from __future__ import annotations


def nport_xml(
    *,
    report_date: str,
    holdings: list[tuple[str, str, str, str]],
    cik: str = "0001067839",
    series_id: str = "S000101292",
    class_id: str = "C000271435",
    fund_name: str = "Invesco QQQ Trust, Series 1",
    namespace: bool = True,
) -> bytes:
    """Return a small NPORT-P document.

    ``holdings`` entries are ``(name, cusip, pct_val, val_usd)``.
    The weights are synthetic even when the fund identifiers match QQQ.
    """

    xmlns = ' xmlns="http://www.sec.gov/edgar/nport"' if namespace else ""
    rows = []
    for name, cusip, pct_val, value in holdings:
        rows.append(
            "<invstOrSec>"
            f"<name>{name}</name>"
            f"<cusip>{cusip}</cusip>"
            f"<balance>10</balance>"
            "<curCd>USD</curCd>"
            f"<valUSD>{value}</valUSD>"
            f"<pctVal>{pct_val}</pctVal>"
            "<assetCat>EC</assetCat>"
            "<invCountry>US</invCountry>"
            "</invstOrSec>"
        )
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission{xmlns}>
  <headerData>
    <submissionType>NPORT-P</submissionType>
    <filerInfo>
      <filer><issuerCredentials><cik>{cik}</cik></issuerCredentials></filer>
      <seriesClassInfo>
        <seriesId>{series_id}</seriesId>
        <classId>{class_id}</classId>
      </seriesClassInfo>
    </filerInfo>
  </headerData>
  <formData>
    <genInfo>
      <regName>{fund_name}</regName>
      <repPdDate>{report_date}</repPdDate>
    </genInfo>
    <invstOrSecs>
      {"".join(rows)}
    </invstOrSecs>
  </formData>
</edgarSubmission>
"""
    return body.encode("utf-8")


EARLIER_XML = nport_xml(
    report_date="2025-03-31",
    holdings=[
        ("Fixture Alpha", "AAAAAA001", "50", "5000000"),
        ("Fixture Beta", "BBBBBB002", "30", "3000000"),
        ("Fixture Gamma", "CCCCCC003", "20", "2000000"),
    ],
)
LATER_XML = nport_xml(
    report_date="2025-06-30",
    holdings=[
        ("Fixture Alpha", "AAAAAA001", "40", "4000000"),
        ("Fixture Beta", "BBBBBB002", "40", "4000000"),
        ("Fixture Gamma", "CCCCCC003", "20", "2000000"),
    ],
)
