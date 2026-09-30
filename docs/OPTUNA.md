# Optuna

Optuna tunes native XGBoost boosters. It does not use `XGBRegressor` or scikit-learn.

See [Experiment Tracking](EXPERIMENT_TRACKING.md) for optional research logs and [Model Lifecycle](MODEL_LIFECYCLE.md) for registration and explicit promotion.

Studies are stored in `data/optuna/optuna.db`. The study name includes the first 12 characters of the dataset fingerprint. A second run reopens the same study without renumbering completed trials. Each invocation requests the configured budget minus the number of completed trials; failed attempts can leave the study below that completed-trial budget until a later invocation.

If the fingerprint stored on a study does not match the current dataset, resume is rejected. Delete that study yourself only when you intend to discard it. The tuning command does not delete studies.

The objective sees training and validation rows only. The final test split is removed before `study.optimize`. Early stopping watches the validation set. Test metrics are computed later by `scripts/train_best_risk_model.py`, after the best trial is frozen.

The default configuration in `configs/experiments/qqq_risk_baseline.toml` uses tree depth 2 to 4, learning rate 0.03 to 0.15, and 80 to 220 boosting rounds. Its budget is 20 trials per study and `nthread` is 1.

A failed trial is stored as failed and the study continues. A failed trial is not a candidate model.

With the processed risk dataset present, run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\tune_risk_models.py
```

The command reads the configuration file and produces `reports/experiments/optuna_summary.json`. It does not register or promote the best trial automatically.
