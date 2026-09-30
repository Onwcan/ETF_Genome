"""Point-in-time join of public holdings onto daily market rows.

A holdings snapshot is usable on trading date ``t`` only when its SEC filing
date is on or before ``t``. The report date is never the join key. For the
June 30, 2026 QQQ portfolio filed on August 28, 2026, a market row dated
August 27, 2026 still uses the previously published snapshot.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.storage.local_store import LocalHoldingsStore
from etf_genome.data.storage.market_store import MarketStore
from etf_genome.data.storage.sync_repository import SyncRepository
from etf_genome.domain.funds import QQQ
from etf_genome.drift import compute_drift
from etf_genome.features.concentration.metrics import compute_concentration
from etf_genome.features.errors import CalculationError
from etf_genome.features.market.series import (
    GENOME_FEATURES,
    MARKET_FEATURES,
    add_forward_targets,
    add_market_features,
)

DATASET_VERSION = "qqq-risk-1"
FEATURE_VERSION = "market-genome-1"
TARGET_VERSION = "fwd-20d-1"
TRAIN_END = date(2023, 12, 31)
VALIDATION_END = date(2024, 12, 31)

_TIMELINE_FLOATS = [
    "reported_weight_sum",
    "top_1_weight",
    "top_5_concentration",
    "top_10_concentration",
    "hhi",
    "holdings_drift",
    "top_10_delta",
    "hhi_delta",
]


def build_risk_dataset(settings: AppSettings) -> tuple[pl.DataFrame, dict[str, object]]:
    """Build the QQQ risk table. Holdings enter only on or after publication."""

    bars = MarketStore(settings).read()
    if bars.is_empty() or "close" not in bars.columns:
        raise ValueError("Market data unavailable.")
    market = add_forward_targets(
        add_market_features(bars),
        tail_threshold=settings.tail_drawdown_threshold,
    ).with_columns(pl.lit(QQQ.fund_id).alias("fund_id"))
    timeline = build_holdings_timeline(settings)
    joined = attach_public_holdings(market, timeline)
    splits = [
        assign_temporal_split(
            row["trading_date"],
            row["label_end_date"],
            row["momentum_120d"],
        )
        for row in joined.iter_rows(named=True)
    ]
    dataset = joined.with_columns(pl.Series("split", splits)).sort("trading_date")
    meta = dataset_metadata(dataset, timeline)
    return dataset, meta


def attach_public_holdings(market: pl.DataFrame, timeline: pl.DataFrame) -> pl.DataFrame:
    """As-of join on ``available_from``. Rows before the first filing stay null."""

    ordered = market.sort("trading_date")
    if timeline.is_empty():
        empty_cols: list[pl.Expr] = [
            pl.lit(None, dtype=pl.Date).alias("report_date"),
            pl.lit(None, dtype=pl.Date).alias("publication_date"),
            pl.lit(None, dtype=pl.Date).alias("available_from"),
            pl.lit(None, dtype=pl.Date).alias("superseded_by"),
            pl.lit(None, dtype=pl.Utf8).alias("accession"),
            pl.lit(None, dtype=pl.Int64).alias("holding_count"),
            pl.lit(None, dtype=pl.Int64).alias("holding_count_delta"),
        ]
        empty_cols.extend(pl.lit(None, dtype=pl.Float64).alias(name) for name in _TIMELINE_FLOATS)
        joined = ordered.with_columns(empty_cols)
    else:
        right = timeline.sort("available_from").unique(subset=["available_from"], keep="last")
        joined = ordered.join_asof(
            right,
            left_on="trading_date",
            right_on="available_from",
            strategy="backward",
        )
    return joined.with_columns(
        (pl.col("trading_date") - pl.col("report_date"))
        .dt.total_days()
        .alias("days_since_holdings_report_date"),
        (pl.col("trading_date") - pl.col("available_from"))
        .dt.total_days()
        .alias("days_since_holdings_publication"),
    )


def assign_temporal_split(
    trading_date: object,
    label_end: object,
    momentum_120d: object,
) -> str:
    """Label a row as warmup, unlabeled target, purged, or a chronological split."""

    if not isinstance(trading_date, date) or momentum_120d is None:
        return "warmup"
    if not isinstance(label_end, date):
        return "no_target"
    if trading_date <= TRAIN_END:
        if label_end > TRAIN_END:
            return "purged_train"
        return "train"
    if trading_date <= VALIDATION_END:
        if label_end > VALIDATION_END:
            return "purged_validation"
        return "validation"
    return "test"


def build_holdings_timeline(settings: AppSettings) -> pl.DataFrame:
    """One row per public QQQ filing, ordered by the date it became usable."""

    store = LocalHoldingsStore(settings)
    filings = [
        filing
        for filing in SyncRepository(store.catalog).list_filings(QQQ.fund_id)
        if filing.report_date and filing.filed_at
    ]
    filings.sort(key=lambda item: (str(item.filed_at), str(item.report_date)))
    rows: list[dict[str, object]] = []
    previous_date: date | None = None
    for index, filing in enumerate(filings):
        report_date = date.fromisoformat(str(filing.report_date))
        available = date.fromisoformat(str(filing.filed_at)[:10])
        frame = store.read_holdings(QQQ.fund_id, report_date)
        try:
            metrics = compute_concentration(frame)
        except CalculationError:
            continue
        drift_value = None
        top_10_delta = None
        hhi_delta = None
        count_delta = None
        if previous_date is not None and previous_date < report_date:
            drift = compute_drift(store.read_holdings(QQQ.fund_id, previous_date), frame)
            drift_value = drift.overall_drift
            top_10_delta = drift.concentration_drift.top_10_delta
            hhi_delta = drift.concentration_drift.hhi_delta
            count_delta = drift.concentration_drift.holdings_count_delta
        successor = filings[index + 1].filed_at if index + 1 < len(filings) else None
        rows.append(
            {
                "report_date": report_date,
                "publication_date": available,
                "available_from": available,
                "superseded_by": None
                if successor is None
                else date.fromisoformat(str(successor)[:10]),
                "accession": filing.accession,
                "holding_count": metrics.holdings_count,
                "reported_weight_sum": metrics.weight_sum,
                "top_1_weight": metrics.top_1_weight,
                "top_5_concentration": metrics.top_5_weight,
                "top_10_concentration": metrics.top_10_weight,
                "hhi": metrics.hhi,
                "holdings_drift": drift_value,
                "top_10_delta": top_10_delta,
                "hhi_delta": hhi_delta,
                "holding_count_delta": count_delta,
            }
        )
        previous_date = report_date
    return _timeline_frame(rows)


def write_dataset(settings: AppSettings) -> dict[str, object]:
    """Persist the feature table, timeline, and metadata sidecar."""

    frame, meta = build_risk_dataset(settings)
    directory = settings.processed_dir / "features"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "qqq_risk_dataset.parquet"
    temporary = path.with_suffix(".parquet.tmp")
    frame.write_parquet(temporary)
    temporary.replace(path)
    timeline = build_holdings_timeline(settings)
    if not timeline.is_empty() and not frame.is_empty():
        first_use = (
            frame.filter(pl.col("accession").is_not_null())
            .group_by("accession")
            .agg(pl.col("trading_date").min().alias("used_from_market_date"))
        )
        timeline = timeline.join(first_use, on="accession", how="left")
    else:
        timeline = timeline.with_columns(pl.lit(None, dtype=pl.Date).alias("used_from_market_date"))
    timeline.write_parquet(directory / "qqq_holdings_timeline.parquet")
    meta["created_at"] = datetime.now(UTC).isoformat()
    (directory / "qqq_risk_dataset_meta.json").write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )
    meta["dataset_file"] = "qqq_risk_dataset.parquet"
    return meta


def dataset_metadata(dataset: pl.DataFrame, timeline: pl.DataFrame) -> dict[str, object]:
    """Fingerprint the table without hashing absolute paths or timestamps."""

    accessions = timeline.get_column("accession").to_list() if timeline.height else []
    dates = dataset.get_column("trading_date").to_list() if dataset.height else []
    split_counts: dict[str, int] = {}
    if dataset.height:
        for key, value in dataset.group_by("split").len().iter_rows():
            split_counts["unlabeled" if key is None else str(key)] = int(value)
    payload: dict[str, object] = {
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "target_version": TARGET_VERSION,
        "market_features": MARKET_FEATURES,
        "genome_features": GENOME_FEATURES,
        "targets": [
            "forward_realized_vol_20d",
            "forward_max_drawdown_20d",
            "tail_event_20d",
        ],
        "availability_rule": (
            "available_from is the SEC filing date; usable when available_from <= trading_date"
        ),
        "row_count": dataset.height,
        "market_rows": int(dataset.filter(pl.col("close").is_not_null()).height),
        "genome_rows": int(dataset.filter(pl.col("holding_count").is_not_null()).height),
        "market_start": None if not dates else str(min(dates)),
        "market_end": None if not dates else str(max(dates)),
        "accessions": accessions,
        "split_counts": split_counts,
        "provider": None
        if dataset.is_empty() or "provider" not in dataset.columns
        else dataset.get_column("provider").drop_nulls().head(1).to_list()[:1],
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    payload["fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return payload


def _timeline_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(
            schema={
                "report_date": pl.Date,
                "publication_date": pl.Date,
                "available_from": pl.Date,
                "superseded_by": pl.Date,
                "accession": pl.Utf8,
                "holding_count": pl.Int64,
                "reported_weight_sum": pl.Float64,
                "top_1_weight": pl.Float64,
                "top_5_concentration": pl.Float64,
                "top_10_concentration": pl.Float64,
                "hhi": pl.Float64,
                "holdings_drift": pl.Float64,
                "top_10_delta": pl.Float64,
                "hhi_delta": pl.Float64,
                "holding_count_delta": pl.Int64,
            }
        )
    return pl.DataFrame(rows).sort("available_from")
