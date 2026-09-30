"""Load stored N-PORT snapshots into a point-in-time graph."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.graph.analytics import crowding, etf_degree, pair_metrics
from etf_genome.graph.snapshot import HoldingsSnapshot, build_graph
from etf_genome.graph.store import write_snapshot
from etf_genome.graph.universe import ResolvedFund


def load_public_filings(
    settings: AppSettings,
    funds: list[ResolvedFund],
) -> dict[str, list[HoldingsSnapshot]]:
    store = LocalHoldingsStore(settings)
    repository = SyncRepository(store.catalog)
    grouped: dict[str, list[HoldingsSnapshot]] = {}
    for fund in funds:
        if fund.status != "resolved":
            continue
        fund_id = f"cik:{fund.cik}|series:{fund.series_id}"
        snapshots: list[HoldingsSnapshot] = []
        for record in repository.list_filings(fund_id):
            if record.report_date is None or record.filed_at is None:
                continue
            report = date.fromisoformat(record.report_date[:10])
            try:
                holdings = store.read_holdings(fund_id, report)
            except Exception:
                continue
            if holdings.is_empty():
                continue
            snapshots.append(
                HoldingsSnapshot(
                    fund_id=fund_id,
                    ticker=fund.ticker,
                    cik=fund.cik,
                    series_id=fund.series_id,
                    class_id=fund.class_id,
                    fund_name=fund.fund_name,
                    report_date=report,
                    available_from=date.fromisoformat(record.filed_at[:10]),
                    accession=record.accession,
                    holdings=holdings,
                )
            )
        grouped[fund_id] = snapshots
    return grouped


def build_persisted_graph(
    settings: AppSettings,
    funds: list[ResolvedFund],
    *,
    as_of: date,
    universe_id: str,
    universe_fingerprint: str,
    min_shared: int = 1,
) -> dict[str, object]:
    filings = load_public_filings(settings, funds)
    nodes, edges, manifest = build_graph(
        filings,
        as_of=as_of,
        universe_id=universe_id,
        universe_fingerprint=universe_fingerprint,
    )
    projection = pl.DataFrame()
    if not edges.is_empty():
        projection = pair_metrics(edges, min_shared=min_shared)
    universe_count = sum(fund.status == "resolved" for fund in funds)
    crowded = crowding(edges, universe_count) if not edges.is_empty() else pl.DataFrame()
    directory = write_snapshot(
        settings,
        universe_id=universe_id,
        as_of=as_of.isoformat(),
        nodes=nodes,
        edges=edges,
        projection=projection,
        crowded=crowded,
        manifest=manifest,
    )
    degree = etf_degree(edges) if not edges.is_empty() else pl.DataFrame()
    if not degree.is_empty():
        degree.write_parquet(directory / "etf_degree.parquet")
    manifest["artifact_dir"] = str(directory)
    return manifest


def quality_report(edges: pl.DataFrame, nodes: pl.DataFrame) -> dict[str, object]:
    if edges.is_empty():
        return {"edges": 0}
    cusip = edges.filter(pl.col("security_node_id").str.starts_with("cusip:")).height
    return {
        "edges": edges.height,
        "cusip_edges": cusip,
        "non_cusip_edges": edges.height - cusip,
        "negative_edges": edges.filter(pl.col("portfolio_weight") < 0).height,
        "missing_weight_edges": edges.filter(pl.col("portfolio_weight").is_null()).height,
        "etf_nodes": 0 if nodes.is_empty() else nodes.filter(pl.col("node_type") == "ETF").height,
        "security_nodes": (
            nodes.filter(pl.col("node_type") == "SECURITY").height if not nodes.is_empty() else 0
        ),
    }


def artifact_dir(path: Path) -> Path:
    return path
