"""Point-in-time ETF-security graph snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

import polars as pl

from etf_genome.domain.identifiers import IdentifierError
from etf_genome.graph.identity import SCHEMA_VERSION, etf_node_id, security_node_id


@dataclass(frozen=True)
class HoldingsSnapshot:
    """One public holdings filing. ``available_from`` is the SEC filing date."""

    fund_id: str
    ticker: str
    cik: str
    series_id: str
    class_id: str
    fund_name: str
    report_date: date
    available_from: date
    accession: str
    holdings: pl.DataFrame


def select_snapshot(
    filings: list[HoldingsSnapshot],
    as_of: date,
) -> HoldingsSnapshot | None:
    """Latest filing whose publication date is on or before ``as_of``."""

    eligible = [item for item in filings if item.available_from <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda item: (item.available_from, item.report_date, item.accession))


def build_graph(
    filings_by_fund: dict[str, list[HoldingsSnapshot]],
    *,
    as_of: date,
    universe_id: str,
    universe_fingerprint: str,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, object]]:
    """Build nodes and edges from filings that were public by ``as_of``."""

    etf_rows: list[dict[str, object]] = []
    edge_rows: list[dict[str, object]] = []
    accessions: list[str] = []
    for fund_id, filings in filings_by_fund.items():
        chosen = select_snapshot(filings, as_of)
        if chosen is None:
            continue
        if chosen.fund_id != fund_id:
            raise ValueError("Filing fund id does not match the universe key.")
        accessions.append(chosen.accession)
        etf_rows.append(
            {
                "node_id": chosen.fund_id,
                "node_type": "ETF",
                "ticker": chosen.ticker,
                "cik": chosen.cik,
                "series_id": chosen.series_id,
                "class_id": chosen.class_id,
                "name": chosen.fund_name,
                "report_date": chosen.report_date,
                "available_from": chosen.available_from,
                "accession": chosen.accession,
            }
        )
        edge_rows.extend(_edges(chosen))
    nodes = _nodes(etf_rows, edge_rows)
    edges = _collapse_edges(edge_rows)
    manifest = _manifest(
        nodes,
        edges,
        as_of=as_of,
        universe_id=universe_id,
        universe_fingerprint=universe_fingerprint,
        accessions=sorted(accessions),
    )
    return nodes, edges, manifest


def _edges(snapshot: HoldingsSnapshot) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in snapshot.holdings.iter_rows(named=True):
        try:
            security_id = security_node_id(
                cusip=record.get("cusip"),
                isin=record.get("isin"),
                ticker=record.get("security_ticker"),
                security_name=record.get("security_name"),
            )
        except IdentifierError:
            continue
        weight = record.get("portfolio_weight")
        rows.append(
            {
                "etf_node_id": snapshot.fund_id,
                "security_node_id": security_id,
                "portfolio_weight": None if weight is None else float(weight),
                "market_value": _optional_float(record.get("market_value")),
                "quantity": _optional_float(record.get("quantity")),
                "currency": record.get("currency"),
                "asset_type": record.get("asset_type"),
                "country": record.get("country"),
                "security_ticker": record.get("security_ticker"),
                "security_name": record.get("security_name"),
                "report_date": snapshot.report_date,
                "publication_date": snapshot.available_from,
                "available_from": snapshot.available_from,
                "accession": snapshot.accession,
                "source": record.get("source") or "sec-nport",
            }
        )
    return rows


def _nodes(etf_rows: list[dict[str, object]], edge_rows: list[dict[str, object]]) -> pl.DataFrame:
    security_rows: dict[str, dict[str, object]] = {}
    for edge in edge_rows:
        security_id = str(edge["security_node_id"])
        current = security_rows.get(security_id)
        if current is None:
            security_rows[security_id] = {
                "node_id": security_id,
                "node_type": "SECURITY",
                "ticker": edge.get("security_ticker"),
                "cik": None,
                "series_id": None,
                "class_id": None,
                "name": edge.get("security_name"),
                "report_date": None,
                "available_from": None,
                "accession": None,
                "asset_type": edge.get("asset_type"),
                "country": edge.get("country"),
            }
    etf_frame = pl.DataFrame(etf_rows, infer_schema_length=None) if etf_rows else pl.DataFrame()
    security_frame = (
        pl.DataFrame(list(security_rows.values()), infer_schema_length=None)
        if security_rows
        else pl.DataFrame()
    )
    if etf_frame.is_empty():
        return security_frame
    if security_frame.is_empty():
        return etf_frame
    return pl.concat([etf_frame, security_frame], how="diagonal_relaxed").sort(
        ["node_type", "node_id"]
    )


def _collapse_edges(rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    frame = pl.DataFrame(rows, infer_schema_length=None)
    return (
        frame.group_by(["etf_node_id", "security_node_id"], maintain_order=True)
        .agg(
            pl.col("portfolio_weight").sum(),
            pl.col("market_value").sum(),
            pl.col("quantity").sum(),
            pl.col("currency").drop_nulls().first(),
            pl.col("asset_type").drop_nulls().first(),
            pl.col("country").drop_nulls().first(),
            pl.col("security_ticker").drop_nulls().first(),
            pl.col("security_name").drop_nulls().first(),
            pl.col("report_date").first(),
            pl.col("publication_date").first(),
            pl.col("available_from").first(),
            pl.col("accession").first(),
            pl.col("source").first(),
        )
        .sort(["etf_node_id", "security_node_id"])
    )


def _manifest(
    nodes: pl.DataFrame,
    edges: pl.DataFrame,
    *,
    as_of: date,
    universe_id: str,
    universe_fingerprint: str,
    accessions: list[str],
) -> dict[str, object]:
    canonical_edges = []
    if not edges.is_empty():
        for row in edges.sort(["etf_node_id", "security_node_id"]).iter_rows(named=True):
            weight = row["portfolio_weight"]
            canonical_edges.append(
                [
                    row["etf_node_id"],
                    row["security_node_id"],
                    None if weight is None else round(float(weight), 8),
                ]
            )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "universe_id": universe_id,
        "universe_fingerprint": universe_fingerprint,
        "snapshot_date": as_of.isoformat(),
        "accessions": accessions,
        "edges": canonical_edges,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    etf_count = 0 if nodes.is_empty() else nodes.filter(pl.col("node_type") == "ETF").height
    security_count = (
        0 if nodes.is_empty() else nodes.filter(pl.col("node_type") == "SECURITY").height
    )
    negative = 0
    missing = 0
    if not edges.is_empty():
        negative = edges.filter(pl.col("portfolio_weight") < 0).height
        missing = edges.filter(pl.col("portfolio_weight").is_null()).height
    return {
        **payload,
        "graph_fingerprint": fingerprint,
        "etf_nodes": etf_count,
        "security_nodes": security_count,
        "edge_count": 0 if edges.is_empty() else edges.height,
        "negative_edges": negative,
        "missing_weight_edges": missing,
    }


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def fund_id_for(cik: str, series_id: str) -> str:
    return etf_node_id(cik=cik, series_id=series_id)
