# Model lifecycle

States are `EXPERIMENT`, `CANDIDATE`, `PRODUCTION`, and `ARCHIVED`.

The local `ModelRegistryService` owns model selection. [Optuna](OPTUNA.md) owns validation tuning; [Experiment Tracking](EXPERIMENT_TRACKING.md) describes optional run logs.

Optuna does not promote a model. The sequence is:

```text
tune on validation
train the frozen best trial
score the untouched test split
register a candidate
promote explicitly
```

`models/registry/registry.json` is the pointer the desktop reads. `RiskInferenceService` asks `ModelRegistryService.get_production_model` for the fund, target, and feature family. If nothing is promoted, it loads compatible baseline files from `models/risk_baseline/` when available. It does not choose the newest file. A source checkout without trained artifacts reports unavailable estimates.

Promotion checks that the artifact loads, the feature list exists, the target matches, and test metrics are present. The previous production model for that target and feature family becomes `ARCHIVED`. A newer candidate stays a candidate until `scripts/promote_model.py` is run.

The standalone frozen-model command saves an experiment artifact and metadata. Register that metadata separately, then explicitly promote the returned model ID and version:

```powershell
.\.venv\Scripts\python.exe scripts\train_best_risk_model.py <study_name>
.\.venv\Scripts\python.exe scripts\register_model.py <model.metadata.json>
.\.venv\Scripts\python.exe scripts\promote_model.py <model_id> <model_version>
```

Replace the angle-bracket placeholders with the configured study name and generated artifact values. Registration copies artifacts into `models/candidates`; promotion copies the selected artifact into `models/production` and updates the registry. These are local model files, independent of MLflow's tracking database. The orchestration `train_candidate` service combines frozen-model training and candidate registration, but still leaves promotion explicit.

The desktop does not run Optuna, MLflow, or W&B, and it does not promote models when a new market bar arrives.

A frozen Windows build copies `models\registry\registry.json`, `models\production`, and the `models\risk_baseline` fallback only when those paths exist locally. Optuna, W&B, and MLflow are not part of that build. See [Windows Packaging](WINDOWS_PACKAGING.md) for build and artifact review instructions.
