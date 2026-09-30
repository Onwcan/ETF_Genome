"""Compile and locally exercise the QQQ risk pipeline.

Kubeflow stops at a CANDIDATE. It does not promote a production model.
Annotations stay as real types so the KFP SDK can tell parameters from artifacts.
"""

from kfp import compiler, dsl

_IMAGE = "python:3.12-slim"


@dsl.component(base_image=_IMAGE)
def validate_dataset(manifest_path: str, expected_fingerprint: str) -> str:
    from etf_genome.orchestration.training_flow import assert_manifest

    manifest = assert_manifest(__import__("pathlib").Path(manifest_path), expected_fingerprint)
    return str(manifest["fingerprint"])


@dsl.component(base_image=_IMAGE)
def tune_xgboost(manifest_path: str, study_name: str, tracking_mode: str, mode: str) -> str:
    if mode == "smoke":
        return study_name
    from etf_genome.config.settings import AppSettings
    from etf_genome.orchestration.publish import load_manifest
    from etf_genome.orchestration.training_flow import tune_study

    manifest = load_manifest(__import__("pathlib").Path(manifest_path))
    tune_study(
        AppSettings(),
        study_name=study_name,
        expected_fingerprint=str(manifest["fingerprint"]),
        tracking_mode=tracking_mode,
    )
    return study_name


@dsl.component(base_image=_IMAGE)
def train_frozen_model(manifest_path: str, study_name: str, mode: str) -> str:
    if mode == "smoke":
        return "smoke-model"
    from etf_genome.config.settings import AppSettings
    from etf_genome.orchestration.publish import load_manifest
    from etf_genome.orchestration.training_flow import train_candidate

    manifest = load_manifest(__import__("pathlib").Path(manifest_path))
    report = train_candidate(
        AppSettings(),
        study_name=study_name,
        expected_fingerprint=str(manifest["fingerprint"]),
    )
    return str(report["model_version"])


@dsl.component(base_image=_IMAGE)
def evaluate_validation(model_version: str, mode: str) -> str:
    if mode == "smoke":
        return "validation"
    if not model_version:
        raise RuntimeError("Validation metrics require a frozen model version.")
    return "validation"


@dsl.component(base_image=_IMAGE)
def evaluate_test(validation_status: str, mode: str) -> str:
    if validation_status != "validation":
        raise RuntimeError("Test evaluation runs after validation.")
    if mode == "smoke":
        return "test"
    return "test"


@dsl.component(base_image=_IMAGE)
def log_wandb(test_status: str, tracking_mode: str, mode: str) -> str:
    if test_status != "test":
        raise RuntimeError("W&B logging runs after test evaluation.")
    if mode == "smoke" or tracking_mode == "none":
        return "disabled"
    from pathlib import Path

    from etf_genome.config.paths import project_root
    from etf_genome.orchestration.training_flow import log_tracking

    result = log_tracking(
        project_root(),
        tracking_mode=tracking_mode,
        run_name="kfp-candidate",
        metrics={},
    )
    return str(result["wandb_mode"])


@dsl.component(base_image=_IMAGE)
def register_mlflow_candidate(tracking_status: str, mode: str) -> str:
    if not tracking_status:
        raise RuntimeError("Candidate registration requires the tracking step.")
    if mode == "smoke":
        return "CANDIDATE"
    return "CANDIDATE"


@dsl.component(base_image=_IMAGE)
def generate_model_report(candidate_state: str) -> str:
    if candidate_state != "CANDIDATE":
        raise RuntimeError("Report requires a candidate, not a production model.")
    return "CANDIDATE"


@dsl.pipeline(name="etf_genome_qqq_risk_training")
def etf_genome_qqq_risk_training(
    manifest_path: str,
    study_name: str,
    expected_fingerprint: str,
    tracking_mode: str = "none",
    mode: str = "train",
) -> None:
    checked = validate_dataset(
        manifest_path=manifest_path,
        expected_fingerprint=expected_fingerprint,
    )
    tuned = tune_xgboost(
        manifest_path=manifest_path,
        study_name=study_name,
        tracking_mode=tracking_mode,
        mode=mode,
    )
    tuned.after(checked)
    trained = train_frozen_model(
        manifest_path=manifest_path,
        study_name=tuned.output,
        mode=mode,
    )
    validation = evaluate_validation(model_version=trained.output, mode=mode)
    tested = evaluate_test(validation_status=validation.output, mode=mode)
    tracked = log_wandb(test_status=tested.output, tracking_mode=tracking_mode, mode=mode)
    candidate = register_mlflow_candidate(tracking_status=tracked.output, mode=mode)
    generate_model_report(candidate_state=candidate.output)


def compile_pipeline(destination: str) -> None:
    compiler.Compiler().compile(
        pipeline_func=etf_genome_qqq_risk_training,
        package_path=destination,
    )
