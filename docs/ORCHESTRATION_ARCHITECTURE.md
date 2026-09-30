# Orchestration architecture

ETF Genome keeps two runtimes apart.

```text
Research / training / orchestration
    Airflow, Kubeflow Pipelines, Optuna, W&B, MLflow

Windows end-user application
    ETFGenome.exe, local cache, production model, RiskInferenceService, PySide6
```

`ETFGenome.exe` does not import Airflow, Kubeflow, Kubernetes, or Docker. The desktop `UpdateCoordinator` still refreshes a local cache. Airflow is the research scheduler. They are not substitutes for each other.

## Responsibilities

Airflow builds and publishes data:

```text
market sync + SEC sync
        -> validate sources
        -> point-in-time dataset
        -> dataset_ready.json
```

Kubeflow consumes that manifest. It tunes, trains, evaluates, and registers a `CANDIDATE`. It does not scrape SEC or Twelve Data, and it does not call promotion.

```text
dataset fingerprint
    -> Optuna study
    -> frozen XGBoost
    -> validation and untouched test
    -> MLflow run id
    -> CANDIDATE
    -> explicit human promotion
    -> PRODUCTION
    -> ETFGenome.exe
```

A new dataset does not start training by itself.

## Environments

Airflow runs in WSL2, not in the Windows desktop virtual environment. Kubeflow component containers are Linux images under `containers/training`. Local pipeline development can use the KFP SDK subprocess runner on Windows when Docker and Kubernetes are unavailable.

Do not write host paths such as a user profile into DAG or component source. Pass data and project roots through `ETF_GENOME_DATA_DIR`, `AIRFLOW_HOME`, and pipeline arguments. `pathlib` resolves them at runtime.

## SQLite ownership

These files are separate databases:

| Database | Owner | Do not share writers across |
| --- | --- | --- |
| `data/catalog.sqlite` | Desktop and Airflow data tasks | Windows app and a WSL DAG at the same time |
| `data/optuna/optuna.db` | Optuna studies | Windows training and WSL training |
| `data/mlflow/mlflow.db` | MLflow | Windows training and a Kubeflow task |
| `$AIRFLOW_HOME/airflow.db` | Airflow metadata | The ETF Genome catalog |

Use one active writer per database. Airflow must not be pointed at `catalog.sqlite`.

## Failure behavior

An Airflow task that fails before publication leaves the previous dataset files in place. A Kubeflow failure may leave a candidate unregistered. It does not change `PRODUCTION` rows in `models/registry/registry.json`. Promotion remains `scripts/promote_model.py`.

## Secrets

SEC contact email and provider API keys stay in environment variables. DAG source does not contain them, and logs must not print them.

## What is not in this phase

Kubernetes deployment, paid cloud schedulers, Evidently, Grafana, and automatic promotion are out of scope. Cluster execution is documented as a future path in `docs/KUBEFLOW.md`.
