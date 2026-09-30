"""Tiny, manually checked shock-graph cases. They do not call the SEC."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from etf_genome.graph.analytics import crowding, pair_metrics
from etf_genome.graph.identity import security_node_id
from etf_genome.graph.shock import run_shock
from etf_genome.graph.snapshot import HoldingsSnapshot, build_graph, select_snapshot
from etf_genome.graph.universe import (
    UniverseEntry,
    load_universe_entries,
    parse_series_class_frame,
    resolve_universe,
    universe_manifest,
)


def test_series_class_resolution_marks_missing_and_ambiguous() -> None:
    catalogue = parse_series_class_frame(
        {
            "fields": ["cik", "seriesId", "classId", "symbol"],
            "data": [
                [1067839, "S000101292", "C000271435", "QQQ"],
                [1, "S1", "C1", "SPY"],
                [2, "S2", "C2", "SPY"],
            ],
        }
    )
    funds = resolve_universe(
        (
            UniverseEntry("QQQ", "growth", True, "reference"),
            UniverseEntry("SPY", "broad", True, "ambiguous"),
            UniverseEntry("NOPE", "missing", True, "absent"),
        ),
        catalogue,
    )
    by_ticker = {fund.ticker: fund for fund in funds}
    assert by_ticker["QQQ"].status == "resolved"
    assert by_ticker["QQQ"].cik == "0001067839"
    assert by_ticker["QQQ"].series_id == "S000101292"
    assert by_ticker["SPY"].status == "ambiguous"
    assert by_ticker["NOPE"].status == "unresolved"
    manifest = universe_manifest("unit", funds, source_url="fixture", source_bytes=10)
    assert manifest["validation_status"] == "INCOMPLETE"
    again = universe_manifest("unit", funds, source_url="fixture", source_bytes=99)
    assert again["universe_fingerprint"] == manifest["universe_fingerprint"]


def test_placeholder_identifiers_are_not_security_ids() -> None:
    assert security_node_id(cusip="N/A", isin="NONE", ticker="AAPL", security_name="Apple") == (
        "ticker:AAPL"
    )


def test_point_in_time_graph_excludes_unpublished_filings() -> None:
    old = _filing("A", date(2026, 3, 31), date(2026, 5, 1), "old", "CUSIPOLD1")
    new = _filing("A", date(2026, 6, 30), date(2026, 8, 28), "new", "CUSIPNEW2")
    other = _filing("B", date(2026, 6, 30), date(2026, 8, 20), "other", "CUSIPOTH3")
    grouped = {"fund-a": [old, new], "fund-b": [other]}
    before = select_snapshot(grouped["fund-a"], date(2026, 8, 27))
    assert before is not None
    assert before.accession == "old"
    _nodes, edges, manifest = build_graph(
        grouped,
        as_of=date(2026, 8, 27),
        universe_id="unit",
        universe_fingerprint="u",
    )
    held = set(edges.filter(pl.col("etf_node_id") == "fund-a").get_column("security_node_id"))
    assert "cusip:CUSIPNEW2" not in held
    assert "cusip:CUSIPOLD1" in held
    after_nodes, after_edges, after = build_graph(
        grouped,
        as_of=date(2026, 8, 28),
        universe_id="unit",
        universe_fingerprint="u",
    )
    held_after = set(
        after_edges.filter(pl.col("etf_node_id") == "fund-a").get_column("security_node_id")
    )
    assert "cusip:CUSIPNEW2" in held_after
    assert after["graph_fingerprint"] != manifest["graph_fingerprint"]
    again_nodes, again_edges, again = build_graph(
        grouped,
        as_of=date(2026, 8, 28),
        universe_id="unit",
        universe_fingerprint="u",
    )
    assert again["graph_fingerprint"] == after["graph_fingerprint"]
    assert again_nodes.height == after_nodes.height
    assert again_edges.height == after_edges.height


def test_overlap_jaccard_cosine_and_crowding() -> None:
    edges = pl.DataFrame(
        {
            "etf_node_id": ["A", "A", "B", "B"],
            "security_node_id": ["s1", "s2", "s1", "s3"],
            "portfolio_weight": [0.5, 0.5, 0.2, 0.8],
            "security_ticker": ["AAA", "BBB", "AAA", "CCC"],
            "security_name": ["A", "B", "A", "C"],
        }
    )
    pairs = pair_metrics(edges)
    row = pairs.row(0, named=True)
    assert row["shared_holding_count"] == 1
    assert row["jaccard"] == 1 / 3
    assert abs(row["weighted_overlap"] - 0.2) < 1e-9
    assert row["weighted_overlap_is_long_only"] is True
    expected = 0.1 / ((0.5**2 + 0.5**2) ** 0.5 * (0.2**2 + 0.8**2) ** 0.5)
    assert abs(row["cosine_similarity"] - expected) < 1e-9
    crowded = crowding(edges, universe_etf_count=2)
    top = crowded.row(0, named=True)
    assert top["security_node_id"] == "s1"
    assert top["etf_count"] == 2
    assert top["universe_etf_count"] == 2


def test_negative_weight_is_not_clamped_in_a_direct_shock() -> None:
    edges = pl.DataFrame(
        {
            "etf_node_id": ["A", "A", "A"],
            "security_node_id": ["long", "short", "other"],
            "portfolio_weight": [0.4, -0.1, 0.7],
            "security_ticker": ["LONG", "SHORT", "OTHER"],
            "security_name": ["L", "S", "O"],
        }
    )
    result = run_shock(
        edges,
        {"LONG": -0.2, "SHORT": -0.5},
        scenario_id="unit",
        snapshot_date=date(2026, 8, 28),
    )
    impact = result.impacts[0]
    assert abs(impact.direct_shock - (-0.03)) < 1e-9
    assert abs(impact.covered_weight - 0.3) < 1e-9
    assert "learned secondary propagation is not implemented" in result.assumptions


def test_desktop_startup_does_not_import_torch() -> None:
    import sys

    import etf_genome.desktop.runner

    assert "torch" not in sys.modules
    assert etf_genome.desktop.runner.main
    text = Path("packaging/windows/ETFGenome.spec").read_text(encoding="utf-8")
    assert '"torch"' in text
    for path in Path("src/etf_genome/desktop").rglob("*.py"):
        assert "import torch" not in path.read_text(encoding="utf-8")
    universe_id, entries = load_universe_entries(Path("configs/graph/etf_universe.toml"))
    enabled = [item.ticker for item in entries if item.enabled]
    assert universe_id == "equity-overlap-1"
    assert 20 <= len(enabled) <= 40
    assert len(enabled) == len(set(enabled))
    assert "QQQ" in enabled


def test_duplicate_edges_sum_and_fingerprint_ignores_paths(tmp_path: Path) -> None:
    filing = HoldingsSnapshot(
        fund_id="fund-a",
        ticker="A",
        cik="0000000001",
        series_id="S1",
        class_id="C1",
        fund_name="A",
        report_date=date(2026, 6, 30),
        available_from=date(2026, 8, 1),
        accession="acc",
        holdings=pl.DataFrame(
            {
                "cusip": ["037833100", "037833100"],
                "isin": [None, None],
                "security_ticker": ["AAPL", "AAPL"],
                "security_name": ["Apple", "Apple"],
                "portfolio_weight": [0.1, 0.2],
                "market_value": [1.0, 2.0],
                "quantity": [1.0, 1.0],
                "currency": ["USD", "USD"],
                "asset_type": ["EC", "EC"],
                "country": ["US", "US"],
                "source": ["sec-nport", "sec-nport"],
            }
        ),
    )
    _nodes, edges, manifest = build_graph(
        {"fund-a": [filing]},
        as_of=date(2026, 8, 2),
        universe_id="unit",
        universe_fingerprint="u",
    )
    assert edges.height == 1
    assert abs(float(edges["portfolio_weight"][0]) - 0.3) < 1e-9
    text = json.dumps(manifest)
    assert str(tmp_path) not in text


def _filing(
    fund_id: str,
    report_date: date,
    available_from: date,
    accession: str,
    cusip: str,
) -> HoldingsSnapshot:
    return HoldingsSnapshot(
        fund_id=f"fund-{fund_id.lower()}",
        ticker=fund_id,
        cik="0000000001",
        series_id="S1",
        class_id="C1",
        fund_name=fund_id,
        report_date=report_date,
        available_from=available_from,
        accession=accession,
        holdings=pl.DataFrame(
            {
                "cusip": [cusip],
                "isin": [None],
                "security_ticker": [cusip[:4]],
                "security_name": [cusip],
                "portfolio_weight": [0.5],
                "market_value": [1.0],
                "quantity": [1.0],
                "currency": ["USD"],
                "asset_type": ["EC"],
                "country": ["US"],
                "source": ["sec-nport"],
            }
        ),
    )
