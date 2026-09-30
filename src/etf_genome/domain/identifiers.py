"""Security and fund identifier helpers.

Tickers change. A CUSIP or ISIN is a better holding key when the source
provides one, and a fund is identified by an internal ``fund_id`` built from
the CIK and series id when the caller does not already have one.
"""

from __future__ import annotations

import re

from etf_genome.errors import EtfGenomeError

_CUSIP_BODY = re.compile(r"^[0-9A-Z*@#]{8}$")


class IdentifierError(EtfGenomeError):
    """Raised when a record cannot be given a stable-enough identifier."""


def _compact(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def normalize_cusip(value: str | None) -> str | None:
    return _compact(value)


def normalize_isin(value: str | None) -> str | None:
    return _compact(value)


def normalize_ticker(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def cusip_check_digit(body: str) -> str:
    """Return the CUSIP check digit for the first eight characters.

    Letters map to A=10 ... Z=35. Odd positions (1-based) contribute their
    value; even positions contribute the digits of ``value * 2``. The check
    digit is the amount required to reach the next multiple of 10.
    """

    compact = _compact(body)
    if compact is None or _CUSIP_BODY.fullmatch(compact[:8]) is None or len(compact) < 8:
        raise IdentifierError("CUSIP check-digit input must contain 8 valid characters")
    total = 0
    for index, character in enumerate(compact[:8], start=1):
        if character.isdigit():
            value = int(character)
        else:
            value = ord(character) - ord("A") + 10
        if index % 2 == 0:
            value *= 2
            total += value // 10 + value % 10
        else:
            total += value
    return str((10 - (total % 10)) % 10)


def cusip_is_valid(value: str | None) -> bool:
    """Return True when ``value`` is a 9-character CUSIP with a matching check digit."""

    compact = normalize_cusip(value)
    if compact is None or len(compact) != 9:
        return False
    if _CUSIP_BODY.fullmatch(compact[:8]) is None or not compact[8].isdigit():
        return False
    try:
        expected = cusip_check_digit(compact[:8])
    except IdentifierError:
        return False
    return compact[8] == expected


def build_security_id(
    *,
    cusip: str | None,
    isin: str | None,
    ticker: str | None,
    security_name: str | None,
) -> str:
    """Build an internal security key from the strongest available identifier.

    Preference order is CUSIP, ISIN, ticker, then name. A name-based key is
    not stable across filings and is only a last resort so the row can still
    be stored honestly.
    """

    cusip_key = normalize_cusip(cusip)
    if cusip_key is not None:
        return f"cusip:{cusip_key}"
    isin_key = normalize_isin(isin)
    if isin_key is not None:
        return f"isin:{isin_key}"
    ticker_key = normalize_ticker(ticker)
    if ticker_key is not None:
        return f"ticker:{ticker_key}"
    if security_name is not None and security_name.strip():
        collapsed = re.sub(r"\s+", " ", security_name.strip().upper())
        return f"name:{collapsed}"
    raise IdentifierError("holding has no cusip, isin, ticker, or name")


def build_fund_id(
    *,
    fund_id: str | None,
    cik: str | None,
    series_id: str | None,
) -> str:
    """Return an explicit fund id, or derive one from CIK plus series id.

    A ticker is intentionally not accepted here. Tickers are reused and are
    not a permanent fund identifier.
    """

    if fund_id is not None and fund_id.strip():
        return fund_id.strip()
    cik_key = _compact(cik)
    series_key = _compact(series_id)
    if cik_key is None or series_key is None:
        raise IdentifierError(
            "fund_id is missing and cannot be derived without both cik and series_id"
        )
    digits = re.sub(r"\D", "", cik_key)
    padded = digits.zfill(10) if digits else cik_key
    return f"cik:{padded}|series:{series_key}"
