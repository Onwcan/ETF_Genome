$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if ($args.Count -ne 1) { throw "Usage: .\scripts\train_best_risk_model.ps1 <study_name>" }
$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python "scripts\train_best_risk_model.py" $args[0]
exit $LASTEXITCODE
