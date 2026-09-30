# Kubeflow Pipelines

Kubeflow Pipelines orchestrates ML work. It consumes a dataset manifest produced by Airflow or by `publish_risk_dataset`. It does not download SEC or market data.

See [Orchestration Architecture](ORCHESTRATION_ARCHITECTURE.md) for runtime boundaries and [Model Lifecycle](MODEL_LIFECYCLE.md) for local registration and explicit promotion.

The pipeline name is `etf_genome_qqq_risk_training`. The Python definition is `orchestration/kubeflow/qqq_risk_pipeline.py`. Compile it; do not edit the generated YAML by hand.

## Components

| Component | Responsibility |
| --- | --- |
| `validate_dataset` | Require `validation_status=PASSED` and the expected fingerprint |
| `tune_xgboost` | Create or resume a persistent Optuna study for one target and feature family |
| `train_frozen_model` | Refit the best trial, score validation and the untouched test, register a candidate |
| `evaluate_validation` | Continue only when a frozen model version exists |
| `evaluate_test` | Continue only after the validation step |
| `log_wandb` | Optional tracking. `none` and smoke mode do not need `WANDB_API_KEY` |
| `register_mlflow_candidate` | Ordering/state marker ending at `CANDIDATE`; registration is already performed by the training service |
| `generate_model_report` | Reject any state other than `CANDIDATE`; return the state marker |

`train_frozen_model` calls the existing `train_candidate` service, which writes validation and test metrics, attempts optional MLflow logging, registers the model in the local file registry, and writes `candidate_report.json`. The later components enforce order; they do not independently recompute those metrics or use MLflow Model Registry. None of them call promotion.

`mode=smoke` walks the graph without Optuna, registry writes, or a W&B key. The dataset-validation component still requires a valid manifest and matching fingerprint. The pipeline defaults to `mode=train`; explicitly select smoke mode for a graph smoke check. Compilation starts neither mode.

Optuna trial execution stays inside one component. Studies use `data/optuna/optuna.db` for local development. Distributed trials are not implemented; deployment plans belong to the [Roadmap](ROADMAP.md#orchestration-deployment).

## Local execution and containers

The training image definition is `containers/training/Dockerfile`. It installs research and ML dependencies without PySide6. The current component decorators use the base image `python:3.12-slim`, with no configured project installation. Wiring an image containing ETF Genome and its dependencies is required before real container execution. Building or executing the supplied image requires a configured Docker environment; the Dockerfile's presence does not verify those operations.

Local SDK subprocess execution requires a usable Unix-style `python3` command and component dependencies, so use a suitable Linux environment. Docker execution requires a running daemon. Cluster submission requires a Kubeflow Pipelines backend, storage configuration, and a reachable Kubernetes environment.

Compilation checks the pipeline definition. It does not verify container execution, dataset access, completed training, or cluster deployment. Those operations need separate evidence from the target environment. Configure storage for MLflow and Optuna outside component source and avoid embedded host-specific paths.

## Compile

The PowerShell helper expects a project-local `.venv-kfp` environment. From the repository root with Python 3.12:

```powershell
py -3.12 -m venv .venv-kfp
.\.venv-kfp\Scripts\python.exe -m pip install -e ".[orchestration-kubeflow]"
.\scripts\orchestration\compile_kfp.ps1
```

The output path is `artifacts/kubeflow/qqq_risk_training_pipeline.yaml`.

See [Validation](VALIDATION.md) for recorded compilation and smoke evidence, and the [Roadmap](ROADMAP.md#orchestration-deployment) for deployment work.
