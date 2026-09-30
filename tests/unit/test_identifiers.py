"""Identifier tests."""

from __future__ import annotations

import pytest

from etf_genome.domain.identifiers import (
    IdentifierError,
    build_fund_id,
    build_security_id,
    cusip_is_valid,
)


def test_cusip_check_digit_accepts_a_known_public_example() -> None:
    assert cusip_is_valid("037833100")
    assert cusip_is_valid("037833101") is False
    assert cusip_is_valid("not-a-cusip") is False


def test_security_id_prefers_cusip_over_ticker() -> None:
    security_id = build_security_id(
        cusip=" abcd00010 ",
        isin="USABCD000108",
        ticker="abcd",
        security_name="Example",
    )
    assert security_id == "cusip:ABCD00010"


def test_security_id_falls_back_to_name() -> None:
    security_id = build_security_id(
        cusip=None,
        isin=" ",
        ticker=None,
        security_name="  North  Wind  ",
    )
    assert security_id == "name:NORTH WIND"


def test_security_id_requires_some_identifier() -> None:
    with pytest.raises(IdentifierError):
        build_security_id(cusip=None, isin=None, ticker=None, security_name="  ")


def test_fund_id_is_not_taken_from_a_ticker() -> None:
    assert build_fund_id(fund_id=" SERIES-1 ", cik=None, series_id=None) == "SERIES-1"
    derived = build_fund_id(fund_id=None, cik="1999999", series_id="s000099999")
    assert derived == "cik:0001999999|series:S000099999"
    with pytest.raises(IdentifierError):
        build_fund_id(fund_id=None, cik=None, series_id=None)
