# Kubeflow Pipelines

Kubeflow Pipelines orchestrates ML work. It consumes a dataset manifest produced by Airflow or by `publish_risk_dataset`. It does not download SEC or market data.

The pipeline name is `etf_genome_qqq_risk_training`. The Python definition is `orchestration/kubeflow/qqq_risk_pipeline.py`. Compile it; do not edit the generated YAML by hand.

## Components

| Component | Responsibility |
| --- | --- |
| `validate_dataset` | Require `validation_status=PASSED` and the expected fingerprint |
| `tune_xgboost` | Resume the existing Optuna study for one target and feature family |
| `train_frozen_model` | Refit the best trial, score validation and the untouched test, register a candidate |
| `evaluate_validation` | Continue only when a frozen model version exists |
| `evaluate_test` | Continue only after the validation step |
| `log_wandb` | Optional tracking. `none` and smoke mode do not need `WANDB_API_KEY` |
| `register_mlflow_candidate` | End state is `CANDIDATE` |
| `generate_model_report` | Reject any state other than `CANDIDATE` |

`train_frozen_model` calls the existing `train_candidate` service, which already writes validation and test metrics and an MLflow run when MLflow imports. The later components enforce order. None of them call promotion.

`mode=smoke` walks the graph without Optuna, without writing the production registry, and without a W&B key. `mode=train` is the real path and must be started explicitly.

Optuna trial execution stays inside one component. Studies still use `data/optuna/optuna.db` for local development. Distributed trial execution is not part of this phase.

## Local execution and containers

The training image definition is `containers/training/Dockerfile`. It installs research and ML dependencies without PySide6. Building and executing the image require a configured Docker environment; the Dockerfile's presence does not verify those operations.

Local SDK subprocess execution requires a usable Unix-style `python3` command and component dependencies, so use a suitable Linux environment. Docker execution requires a running daemon. Cluster submission requires a Kubeflow Pipelines backend, storage configuration, and a reachable Kubernetes environment.

Compilation checks the pipeline definition. It does not verify container execution, dataset access, completed training, or cluster deployment. Those operations need separate evidence from the target environment. Configure storage for MLflow and Optuna outside component source and avoid embedded host-specific paths.

## Compile

With a separate virtual environment that has the `orchestration-kubeflow` extra:

```powershell
.\scripts\orchestration\compile_kfp.ps1
```

The output path is `artifacts/kubeflow/qqq_risk_training_pipeline.yaml`.
