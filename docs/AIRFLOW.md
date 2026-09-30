# Airflow

The Airflow foundation defines research data DAGs. It is separate from `ETFGenome.exe`; the desktop uses its own local background coordinator. See [Orchestration Architecture](ORCHESTRATION_ARCHITECTURE.md) for service and database ownership.

The project targets a dedicated Linux or WSL2 environment with Python 3.12 for Airflow. Keep it separate from the desktop `.venv` and leave the distribution's system interpreter unchanged.

The metadata database is `$AIRFLOW_HOME/airflow.db`. That is not `data/catalog.sqlite`.

## DAGs

The DAG file is `orchestration/airflow/dags/etf_genome_dags.py`.

| DAG | Tasks | What it calls |
| --- | --- | --- |
| `etf_genome_market_sync` | 5 | `sync_qqq_market`, then local bar and provenance checks |
| `etf_genome_sec_sync` | 3 | `UpdateCoordinator.sync_sec`, then the holdings timeline |
| `etf_genome_risk_dataset` | 4 | readiness checks, then staged dataset publication |

`catchup` is false, `schedule` is unset, and each DAG retries at most once after 15 minutes. Provider HTTP backoff stays inside the existing clients. Do not raise the DAG retry count to work around rate limits.

The definitions also limit each DAG to one active run. A configured scheduler or manual trigger is required to execute them; DAG presence alone does not provide a deployed schedule.

SEC discovery, download, parse, normalize, and persist stay inside `SecNportSync.run`. Splitting those into separate Airflow tasks would repeat SEC requests. The following task only rebuilds the local holdings timeline.

The dataset DAG does not download market data or filings. It publishes `dataset_ready.json` only after the point-in-time check passes. A failed check does not replace the previous parquet file.

## Local development

Open the checkout from WSL using its resolved platform path, then run the commands from the repository root. Set `PYTHONPATH` to `src` and `AIRFLOW_HOME` to `orchestration/airflow/home`. Do not embed a username or mounted-drive path in configuration. Avoid running the Windows desktop sync and a WSL DAG against the same SQLite catalog at the same time.

```bash
export AIRFLOW_HOME="$PWD/orchestration/airflow/home"
export PYTHONPATH="$PWD/src"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/orchestration/airflow/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"
```

After making Python 3.12 available in the research environment, use a dedicated virtual environment. These setup commands require verification in the target Linux/WSL environment:

```bash
python3.12 -m venv .venv-airflow
.venv-airflow/bin/pip install -e ".[orchestration-airflow]"
.venv-airflow/bin/airflow db migrate
.venv-airflow/bin/airflow dags list
```

`scripts/orchestration/airflow_check.sh` imports the three DAGs when the project-local `.venv-airflow` exists. Successful imports establish DAG loadability; they do not establish a running scheduler, successful live ingestion, or production deployment. Check those boundaries separately in your own environment.

Do not put API keys or the SEC contact email in the DAG file. The tasks construct `AppSettings` from the environment.

Scheduler, storage, and deployment validation belong to the [orchestration deployment roadmap](ROADMAP.md#orchestration-deployment). [Validation](VALIDATION.md) is the home for recorded checks.
