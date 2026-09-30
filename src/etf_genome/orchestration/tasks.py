"""Service wrappers used by Airflow. They do not train or promote models."""

from __future__ import annotations

from datetime import date

import polars as pl

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.market_sync import sync_qqq_market
from etf_genome.data.storage.market_store import MarketStore
from etf_genome.features.risk.dataset import build_holdings_timeline
from etf_genome.orchestration.publish import DatasetNotReady, publish_risk_dataset
from etf_genome.services.runtime import build_update_coordinator


def resolve_configuration() -> dict[str, str]:
    settings = AppSettings()
    return {
        "data_dir": str(settings.resolved_data_dir),
        "offline": str(settings.offline_mode).lower(),
    }


def sync_authoritative_market(settings: AppSettings | None = None) -> dict[str, object]:
    """Download missing Twelve Data bars through the existing sync service."""

    active = settings or AppSettings()
    result = sync_qqq_market(active)
    frame = MarketStore(active).read()
    summary = validate_canonical_bars(frame)
    summary["sync_status"] = result.status
    summary["new_bars"] = result.new_bars
    summary["received_bars"] = result.received_bars
    return summary


def validate_canonical_bars(frame: pl.DataFrame) -> dict[str, object]:
    if frame.is_empty() or "trading_date" not in frame.columns:
        raise DatasetNotReady("Canonical market history is empty.")
    dates = frame.get_column("trading_date").to_list()
    if any(not isinstance(item, date) for item in dates):
        raise DatasetNotReady("Market history has a non-date session.")
    ordered = sorted(dates)
    if dates != ordered:
        raise DatasetNotReady("Market history is not in session order.")
    if len(set(dates)) != len(dates):
        raise DatasetNotReady("Market history has a duplicate session.")
    return {
        "rows": frame.height,
        "latest": str(max(dates)),
        "provider": "twelvedata",
    }


def verify_provenance(frame: pl.DataFrame) -> dict[str, object]:
    if "provider" not in frame.columns:
        raise DatasetNotReady("Market history has no provider column.")
    providers = {
        str(value) for value in frame.get_column("provider").drop_nulls().unique().to_list()
    }
    if providers != {"twelvedata"}:
        raise DatasetNotReady(f"Training bars must stay on Twelve Data, found {sorted(providers)}.")
    return {"provider": "twelvedata", "rows": frame.height}


def sync_filings(settings: AppSettings | None = None) -> dict[str, object]:
    """Discover and ingest missing N-PORT filings through SecNportSync."""

    active = settings or AppSettings()
    coordinator = build_update_coordinator(active)
    try:
        outcome = coordinator.sync_sec("manual")
    finally:
        coordinator.close()
    return {
        "status": outcome.status,
        "discovered": outcome.filings_discovered,
        "ingested": outcome.filings_ingested,
        "skipped": outcome.filings_skipped,
        "changed": outcome.changed,
    }


def recalculate_genome_features(settings: AppSettings | None = None) -> dict[str, int]:
    timeline = build_holdings_timeline(settings or AppSettings())
    return {"timeline_rows": timeline.height}


def require_market_ready(settings: AppSettings | None = None) -> dict[str, object]:
    frame = MarketStore(settings or AppSettings()).read()
    summary = validate_canonical_bars(frame)
    verify_provenance(frame)
    return summary


def require_holdings_ready(settings: AppSettings | None = None) -> dict[str, int]:
    return recalculate_genome_features(settings)


def publish_dataset(settings: AppSettings | None = None) -> dict[str, object]:
    """Publish a new dataset only after point-in-time validation."""

    return publish_risk_dataset(settings or AppSettings())


def run_market_task(task_id: str, settings: AppSettings | None = None) -> dict[str, object]:
    if task_id == "resolve_configuration":
        return dict(resolve_configuration())
    if task_id == "sync_authoritative_market":
        return sync_authoritative_market(settings)
    active = settings or AppSettings()
    frame = MarketStore(active).read()
    if task_id == "validate_canonical_bars":
        return validate_canonical_bars(frame)
    if task_id == "verify_provenance":
        return verify_provenance(frame)
    if task_id == "update_freshness":
        summary = validate_canonical_bars(frame)
        summary["freshness"] = "checked"
        return summary
    raise KeyError(task_id)


def run_sec_task(task_id: str, settings: AppSettings | None = None) -> dict[str, object]:
    if task_id == "resolve_configuration":
        return dict(resolve_configuration())
    if task_id == "sync_filings":
        return sync_filings(settings)
    if task_id == "recalculate_genome_features":
        return dict(recalculate_genome_features(settings))
    raise KeyError(task_id)


def run_dataset_task(task_id: str, settings: AppSettings | None = None) -> dict[str, object]:
    if task_id == "require_market_ready":
        return require_market_ready(settings)
    if task_id == "require_holdings_ready":
        return dict(require_holdings_ready(settings))
    if task_id == "build_dataset":
        return publish_dataset(settings)
    if task_id == "publish_dataset":
        from etf_genome.orchestration.publish import load_manifest

        active = settings or AppSettings()
        manifest = load_manifest(active.processed_dir / "features" / "dataset_ready.json")
        if manifest.get("validation_status") != "PASSED":
            raise DatasetNotReady("Dataset publication did not pass validation.")
        return manifest
    raise KeyError(task_id)
