# Model lifecycle

States are `EXPERIMENT`, `CANDIDATE`, `PRODUCTION`, and `ARCHIVED`.

Optuna does not promote a model. The sequence is:

```text
tune on validation
train the frozen best trial
score the untouched test split
register a candidate
promote explicitly
```

`models/registry/registry.json` is the pointer the desktop reads. `RiskInferenceService` asks `ModelRegistryService.get_production_model` for the fund, target, and feature family. If nothing is promoted, it loads the existing Phase 4 files in `models/risk_baseline/`. It does not choose the newest file.

Promotion checks that the artifact loads, the feature list exists, the target matches, and test metrics are present. The previous production model for that target and feature family becomes `ARCHIVED`. A newer candidate stays a candidate until `scripts/promote_model.py` is run.

The desktop does not run Optuna, MLflow, or W&B, and it does not promote models when a new market bar arrives.

A frozen Windows build copies `models\registry\registry.json` and `models\production` when those paths exist, and it still copies `models\risk_baseline` as the fallback. Optuna, W&B, and MLflow are not part of that build.
