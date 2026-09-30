"""Holdings become usable on the filing date, not the portfolio report date."""

from __future__ import annotations

from datetime import date

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.domain.funds import QQQ
from etf_genome.domain.models import FundMetadata
from etf_genome.features.risk.dataset import attach_public_holdings, build_holdings_timeline


def _timeline() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_date": [date(2026, 3, 31), date(2026, 6, 30)],
            "publication_date": [date(2026, 5, 28), date(2026, 8, 28)],
            "available_from": [date(2026, 5, 28), date(2026, 8, 28)],
            "superseded_by": [date(2026, 8, 28), None],
            "accession": ["march-filing", "june-filing"],
            "holding_count": [102, 105],
            "top_10_concentration": [0.47, 0.45],
        }
    )


def _market(days: list[date]) -> pl.DataFrame:
    return pl.DataFrame({"trading_date": days, "close": [100.0] * len(days)})


def test_june_filing_is_not_used_before_publication() -> None:
    joined = attach_public_holdings(
        _market(
            [
                date(2026, 5, 1),
                date(2026, 6, 30),
                date(2026, 7, 1),
                date(2026, 8, 27),
                date(2026, 8, 28),
            ]
        ),
        _timeline(),
    ).sort("trading_date")
    accessions = joined.get_column("accession").to_list()
    assert accessions[0] is None
    assert accessions[1:] == ["march-filing", "march-filing", "march-filing", "june-filing"]
    june_weight = 0.45
    before = joined.filter(pl.col("trading_date") == date(2026, 8, 27))
    assert before.get_column("top_10_concentration").item() != june_weight
    assert before.get_column("accession").item() == "march-filing"
    after = joined.filter(pl.col("trading_date") == date(2026, 8, 28))
    assert after.get_column("accession").item() == "june-filing"
    assert after.get_column("days_since_holdings_publication").item() == 0


def test_timeline_records_publication_before_use(settings: AppSettings) -> None:
    store = LocalHoldingsStore(settings)
    metadata = FundMetadata(fund_id=QQQ.fund_id, name=QQQ.name, ticker="QQQ", cik=QQQ.cik)
    for report, weights in (
        (date(2026, 3, 31), [0.5, 0.5]),
        (date(2026, 6, 30), [0.7, 0.3]),
    ):
        store.write_holdings(_holdings(report, weights), metadata)
    repository = SyncRepository(store.catalog)
    repository.record_filing(
        accession="0001",
        fund_id=QQQ.fund_id,
        cik=QQQ.cik,
        series_id=QQQ.series_id,
        class_id=QQQ.class_id,
        report_date="2026-03-31",
        filed_at="2026-05-28",
        primary_document="primary_doc.xml",
        source_url="https://www.sec.gov/example",
        content_hash="a" * 64,
        raw_path="",
        parser_version="test",
        downloaded_at="2026-05-28T00:00:00+00:00",
        holding_count=2,
    )
    repository.record_filing(
        accession="0002",
        fund_id=QQQ.fund_id,
        cik=QQQ.cik,
        series_id=QQQ.series_id,
        class_id=QQQ.class_id,
        report_date="2026-06-30",
        filed_at="2026-08-28",
        primary_document="primary_doc.xml",
        source_url="https://www.sec.gov/example",
        content_hash="b" * 64,
        raw_path="",
        parser_version="test",
        downloaded_at="2026-08-28T00:00:00+00:00",
        holding_count=2,
    )
    timeline = build_holdings_timeline(settings).sort("available_from")
    assert timeline.get_column("available_from").to_list() == [date(2026, 5, 28), date(2026, 8, 28)]
    assert timeline.get_column("report_date").to_list() == [date(2026, 3, 31), date(2026, 6, 30)]
    assert timeline.get_column("superseded_by").to_list()[0] == date(2026, 8, 28)
    assert timeline.get_column("holdings_drift")[0] is None
    assert timeline.get_column("holdings_drift")[1] is not None


def _holdings(snapshot: date, weights: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "snapshot_date": [snapshot, snapshot],
            "fund_id": [QQQ.fund_id, QQQ.fund_id],
            "security_id": ["sec-a", "sec-b"],
            "security_name": ["Alpha", "Beta"],
            "portfolio_weight": weights,
            "source": ["test", "test"],
        }
    )
