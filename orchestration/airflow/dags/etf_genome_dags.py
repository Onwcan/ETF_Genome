"""Airflow DAGs for data orchestration.

Load this folder as the Airflow dags directory. The desktop application does
not import it. These DAGs do not train or promote models.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG

try:
    from airflow.operators.python import PythonOperator
except ImportError:  # Airflow 3 moved the operator.
    from airflow.providers.standard.operators.python import PythonOperator

from etf_genome.orchestration.graphs import DATASET_REFRESH, MARKET_SYNC, SEC_SYNC, DagSpec
from etf_genome.orchestration.tasks import run_dataset_task, run_market_task, run_sec_task


def build_dag(spec: DagSpec, runner: object) -> DAG:
    if not callable(runner):
        raise TypeError("DAG runner must be callable.")

    def _callable(task_id: str):
        def _run() -> dict[str, object]:
            return runner(task_id)

        return _run

    with DAG(
        dag_id=spec.dag_id,
        start_date=datetime(2026, 9, 26),
        schedule=spec.schedule,
        catchup=spec.catchup,
        max_active_runs=1,
        default_args={
            "retries": spec.retries,
            "retry_delay": timedelta(minutes=spec.retry_delay_minutes),
        },
        tags=["etf-genome"],
    ) as dag:
        operators = {
            task.task_id: PythonOperator(
                task_id=task.task_id,
                python_callable=_callable(task.task_id),
            )
            for task in spec.tasks
        }
        for task in spec.tasks:
            for upstream in task.upstream:
                operators[upstream] >> operators[task.task_id]
    return dag


market_sync = build_dag(MARKET_SYNC, run_market_task)
sec_sync = build_dag(SEC_SYNC, run_sec_task)
risk_dataset = build_dag(DATASET_REFRESH, run_dataset_task)
