#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
if [[ ! -x .venv-airflow/bin/python ]]; then
  echo "Airflow environment .venv-airflow is missing." >&2
  echo "Create it inside WSL with Python 3.12, then install the orchestration-airflow extra." >&2
  exit 1
fi
export AIRFLOW_HOME="${AIRFLOW_HOME:-$ROOT/orchestration/airflow/home}"
export PYTHONPATH="$ROOT/src"
mkdir -p "$AIRFLOW_HOME"
.venv-airflow/bin/python -c "import airflow; from orchestration.airflow.dags.etf_genome_dags import market_sync, sec_sync, risk_dataset; print(airflow.__version__); print(market_sync.dag_id, len(market_sync.tasks)); print(sec_sync.dag_id, len(sec_sync.tasks)); print(risk_dataset.dag_id, len(risk_dataset.tasks)); print('catchup', market_sync.catchup)"
