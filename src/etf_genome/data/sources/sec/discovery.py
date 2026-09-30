"""Discover NPORT-P filings from one SEC submissions document."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from etf_genome.errors import EtfGenomeError


class DiscoveryError(EtfGenomeError):
    """Raised when a submissions document cannot be read as filing metadata."""


@dataclass(frozen=True)
class DiscoveredFiling:
    """One NPORT-P filing named by the SEC submissions index."""

    cik: str
    accession: str
    filed_at: str | None
    report_date: str | None
    primary_document: str


def discover_nport_filings(payload: object, *, cik: str) -> list[DiscoveredFiling]:
    """Return NPORT-P rows from the ``filings.recent`` columns of one CIK.

    The submissions document is columnar: each field is a list aligned by
    index. Other form types are ignored. Accession numbers come from the
    document, not from a hard-coded list.
    """

    if not isinstance(payload, dict):
        raise DiscoveryError("SEC submissions payload was not a JSON object")
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        raise DiscoveryError("SEC submissions payload has no filings object")
    recent = filings.get("recent")
    if not isinstance(recent, dict):
        raise DiscoveryError("SEC submissions payload has no recent filings")
    forms = _column(recent, "form")
    accessions = _column(recent, "accessionNumber")
    filed = _column(recent, "filingDate")
    reports = _column(recent, "reportDate")
    documents = _column(recent, "primaryDocument")
    width = len(forms)
    if not all(len(column) == width for column in (accessions, filed, reports, documents)):
        raise DiscoveryError("SEC submissions columns do not have equal length")

    discovered: list[DiscoveredFiling] = []
    padded = "".join(character for character in cik if character.isdigit()).zfill(10)
    for index, form in enumerate(forms):
        if str(form).upper() != "NPORT-P":
            continue
        accession = str(accessions[index]).strip()
        document = str(documents[index]).strip()
        document_rejected = _unsafe_document(document) or _unsafe_accession(accession)
        if not accession or not document or document_rejected:
            continue
        report = _optional_text(reports[index])
        discovered.append(
            DiscoveredFiling(
                cik=padded,
                accession=accession,
                filed_at=_optional_text(filed[index]),
                report_date=report,
                primary_document=document,
            )
        )
    discovered.sort(key=lambda item: (item.report_date or "", item.accession), reverse=True)
    return discovered


def choose_filing_xml(index_payload: object) -> str | None:
    """Pick the N-PORT XML name from an SEC filing index.json payload."""

    if not isinstance(index_payload, dict):
        return None
    directory = index_payload.get("directory")
    items = directory.get("item") if isinstance(directory, dict) else None
    if isinstance(items, dict):
        items = [items]
    names: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.append(item["name"])
    xml_names = [
        name for name in names if name.lower().endswith(".xml") and not _unsafe_document(name)
    ]
    preferred = [
        name for name in xml_names if name.lower().endswith("primary_doc.xml") and "/" not in name
    ]
    if not preferred:
        preferred = [
            name for name in xml_names if "primary" in name.lower() and "xsl" not in name.lower()
        ]
    if preferred:
        return preferred[0]
    if xml_names:
        return xml_names[0]
    return None


def filing_document_url(cik: str, accession: str, document: str) -> str:
    """Build the HTTPS archive URL for one filing document."""

    if _unsafe_document(document) or _unsafe_accession(accession):
        raise DiscoveryError("Filing document path is not a relative SEC archive path")
    cik_digits = str(int("".join(character for character in cik if character.isdigit())))
    accession_compact = accession.replace("-", "")
    safe_document = "/".join(quote(part, safe="._-+") for part in document.split("/"))
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_digits}/{accession_compact}/{safe_document}"
    )


def _column(recent: dict[str, object], name: str) -> list[object]:
    value = recent.get(name)
    if not isinstance(value, list):
        raise DiscoveryError(f"SEC submissions field {name} is missing")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unsafe_accession(value: str) -> bool:
    return "/" in value or _unsafe_document(value)


def _unsafe_document(value: str) -> bool:
    """Reject traversal and off-site names. A relative SEC folder/file path is allowed."""

    if value == "" or value.startswith(("/", "\\")) or "\\" in value:
        return True
    if value.startswith(("http:", "https:")):
        return True
    return any(part in {"", ".", ".."} for part in value.split("/"))
