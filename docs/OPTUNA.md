# Optuna

Optuna tunes native XGBoost boosters. It does not use `XGBRegressor` or scikit-learn.

Studies are stored in `data/optuna/optuna.db`. The study name includes the first 12 characters of the dataset fingerprint. A second run of the tuning command continues the same study until the configured trial budget is reached. It does not renumber completed trials.

If the fingerprint stored on a study does not match the current dataset, resume is rejected. Delete that study yourself only when you intend to discard it. The tuning command does not delete studies.

The objective sees training and validation rows only. The final test split is removed before `study.optimize`. Early stopping watches the validation set. Test metrics are computed later by `scripts/train_best_risk_model.py`, after the best trial is frozen.

The search is intentionally small: tree depth 2 to 4, learning rate 0.03 to 0.15, and 80 to 220 boosting rounds. The configured budget is 20 trials per study. `nthread` is 1.

A failed trial is stored as failed and the study continues. A failed trial is not a candidate model.
