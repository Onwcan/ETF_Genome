"""SEC submissions discovery tests."""

from __future__ import annotations

import pytest

from etf_genome.data.sources.sec.discovery import (
    DiscoveryError,
    choose_filing_xml,
    discover_nport_filings,
    filing_document_url,
)


def _payload() -> dict[str, object]:
    return {
        "filings": {
            "recent": {
                "form": ["10-K", "NPORT-P", "8-K", "NPORT-P"],
                "accessionNumber": [
                    "0001067839-25-000001",
                    "0001067839-25-000090",
                    "0001067839-25-000003",
                    "0001067839-25-000080",
                ],
                "filingDate": ["2025-01-01", "2025-08-28", "2025-02-01", "2025-05-29"],
                "reportDate": ["2024-12-31", "2025-06-30", "", "2025-03-31"],
                "primaryDocument": ["cover.htm", "later.xml", "note.htm", "../escape.xml"],
            }
        }
    }


def test_discovery_keeps_only_nport_and_drops_unsafe_names() -> None:
    found = discover_nport_filings(_payload(), cik="1067839")
    assert [item.accession for item in found] == ["0001067839-25-000090"]
    assert found[0].report_date == "2025-06-30"
    assert found[0].filed_at == "2025-08-28"
    assert found[0].cik == "0001067839"


def test_nested_primary_document_is_kept() -> None:
    payload = _payload()
    recent = payload["filings"]["recent"]
    assert isinstance(recent, dict)
    recent["form"].append("NPORT-P")
    recent["accessionNumber"].append("0001067839-26-000030")
    recent["filingDate"].append("2026-08-28")
    recent["reportDate"].append("2026-06-30")
    recent["primaryDocument"].append("xslFormNPORT-P_X01/primary_doc.xml")
    found = discover_nport_filings(payload, cik="0001067839")
    assert found[0].primary_document == "xslFormNPORT-P_X01/primary_doc.xml"
    assert filing_document_url(
        "0001067839",
        "0001067839-26-000030",
        "xslFormNPORT-P_X01/primary_doc.xml",
    ).endswith("/000106783926000030/xslFormNPORT-P_X01/primary_doc.xml")


def test_archive_url_uses_the_accession_from_the_index() -> None:
    url = filing_document_url("0001067839", "0001067839-25-000090", "later.xml")
    assert url == ("https://www.sec.gov/Archives/edgar/data/1067839/000106783925000090/later.xml")


def test_archive_url_rejects_a_remote_document_name() -> None:
    with pytest.raises(DiscoveryError):
        filing_document_url("0001067839", "0001067839-25-000090", "https://example.com/x.xml")


def test_index_accepts_a_single_item_object() -> None:
    payload = {"directory": {"item": {"name": "primary_doc.xml", "type": "text.gif"}}}
    assert choose_filing_xml(payload) == "primary_doc.xml"


def test_uneven_columns_are_rejected() -> None:
    payload = _payload()
    recent = payload["filings"]["recent"]
    assert isinstance(recent, dict)
    recent["form"] = ["NPORT-P"]
    with pytest.raises(DiscoveryError, match="equal length"):
        discover_nport_filings(payload, cik="0001067839")
