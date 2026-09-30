$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if ($args.Count -ne 2) { throw "Usage: .\scripts\promote_model.ps1 <model_id> <model_version>" }
$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python "scripts\promote_model.py" $args[0] $args[1]
exit $LASTEXITCODE
