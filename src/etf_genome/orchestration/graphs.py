"""Task graphs shared by the Airflow DAG files and the unit tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    upstream: tuple[str, ...] = ()


@dataclass(frozen=True)
class DagSpec:
    dag_id: str
    tasks: tuple[TaskSpec, ...]
    catchup: bool = False
    retries: int = 1
    retry_delay_minutes: int = 15
    schedule: str | None = None

    def task_ids(self) -> tuple[str, ...]:
        return tuple(task.task_id for task in self.tasks)


MARKET_SYNC = DagSpec(
    dag_id="etf_genome_market_sync",
    tasks=(
        TaskSpec("resolve_configuration"),
        TaskSpec("sync_authoritative_market", ("resolve_configuration",)),
        TaskSpec("validate_canonical_bars", ("sync_authoritative_market",)),
        TaskSpec("verify_provenance", ("validate_canonical_bars",)),
        TaskSpec("update_freshness", ("verify_provenance",)),
    ),
)

SEC_SYNC = DagSpec(
    dag_id="etf_genome_sec_sync",
    tasks=(
        TaskSpec("resolve_configuration"),
        TaskSpec("sync_filings", ("resolve_configuration",)),
        TaskSpec("recalculate_genome_features", ("sync_filings",)),
    ),
)

DATASET_REFRESH = DagSpec(
    dag_id="etf_genome_risk_dataset",
    tasks=(
        TaskSpec("require_market_ready"),
        TaskSpec("require_holdings_ready"),
        TaskSpec("build_dataset", ("require_market_ready", "require_holdings_ready")),
        TaskSpec("publish_dataset", ("build_dataset",)),
    ),
)

DAGS = (MARKET_SYNC, SEC_SYNC, DATASET_REFRESH)
