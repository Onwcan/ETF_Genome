# Experiment tracking

Weights & Biases is the research log. MLflow is the local run record. Neither is required to train, and neither is part of `ETFGenome.exe`.

## Weights & Biases

The default tracking mode in `configs/experiments/qqq_risk_baseline.toml` is `none`.

`--tracking` is selected by that file, not by a cloud login. When tracking is `wandb` or `all` and `WANDB_API_KEY` is absent, the run uses W&B offline mode. Offline files stay under `artifacts/wandb/`. A W&B failure is recorded and does not delete the model.

Do not put `WANDB_API_KEY` in the repository, model metadata, or the executable. Raw SEC and market files are not uploaded.

## MLflow

Local tracking uses `data/mlflow/mlflow.db` (SQLite) and `artifacts/mlflow/`. The path does not depend on the shell's current directory.

`scripts/mlflow_ui.ps1` opens the local UI at `http://127.0.0.1:5000`. That UI is for research. The desktop application does not start it and does not need it.

## What is logged

Parameters, validation metrics, the dataset fingerprint, the feature family, and the model file. Test metrics are logged only by the frozen-model command, after tuning has finished.
