# Experiment tracking

Weights & Biases is the research log. MLflow is the local run record. Neither is required to train, and neither is part of `ETFGenome.exe`.

See [Optuna](OPTUNA.md) for validation-only tuning and [Model Lifecycle](MODEL_LIFECYCLE.md) for the separate local model registry.

## Weights & Biases

The default tracking mode in `configs/experiments/qqq_risk_baseline.toml` is `none`.

The file's `tracking` field controls the research tracker; the tuning script does not expose a `--tracking` flag. When tracking is `wandb` or `all`, W&B runs offline unless both `WANDB_MODE=online` and `WANDB_API_KEY` are set. Offline files stay under `artifacts/wandb/`. A W&B failure is recorded and does not delete the model.

Do not put `WANDB_API_KEY` in the repository, model metadata, or the executable. Raw SEC and market files are not uploaded.

## MLflow

Local tracking uses `data/mlflow/mlflow.db` (SQLite) and `artifacts/mlflow/`. The path does not depend on the shell's current directory.

The frozen-model workflow attempts MLflow logging when MLflow is importable, independently of the W&B `tracking` field. When MLflow is unavailable, the model can still be saved. The logged run ID is optional provenance; production selection belongs to `models/registry/registry.json`, not to MLflow Model Registry.

`scripts/mlflow_ui.ps1` opens the local UI at `http://127.0.0.1:5000`. That UI is for research. The desktop application does not start it and does not need it.

## What is logged

The W&B tuning summary records experiment metadata and the best validation score. Frozen-model MLflow runs record parameters, validation and test metrics, the dataset fingerprint, the feature family, and the model file. Test metrics are computed only after the best validation trial is frozen; they do not enter the Optuna objective.
