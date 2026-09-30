$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Mlflow = Join-Path $Root ".venv\Scripts\mlflow.exe"
if (-not (Test-Path $Mlflow)) {
    throw "MLflow is not installed in .venv. This UI is for research only."
}
$Database = Join-Path $Root "data\mlflow\mlflow.db"
if (-not (Test-Path $Database)) {
    throw "No local MLflow database at data\mlflow\mlflow.db. Train a candidate first."
}
$Uri = "sqlite:///" + ((Resolve-Path $Database).Path -replace '\\','/')
Write-Output "Local research UI. ETFGenome.exe does not use this server."
& $Mlflow ui --backend-store-uri $Uri --host 127.0.0.1 --port 5000
exit $LASTEXITCODE
