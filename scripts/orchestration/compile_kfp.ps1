$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root
$Python = Join-Path $Root ".venv-kfp\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Kubeflow environment .venv-kfp is missing. Create it with Python 3.12 and install the orchestration-kubeflow extra."
}
New-Item -ItemType Directory -Force -Path "artifacts\kubeflow" | Out-Null
& $Python -c "from orchestration.kubeflow.qqq_risk_pipeline import compile_pipeline; compile_pipeline(r'artifacts/kubeflow/qqq_risk_training_pipeline.yaml')"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Compiled artifacts\kubeflow\qqq_risk_training_pipeline.yaml"
