$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if ($args.Count -ne 1) { throw "Usage: .\scripts\train_graph_baseline.ps1 YYYY-MM-DD" }
& (Join-Path $Root ".venv-graph\Scripts\python.exe") "scripts\train_graph_baseline.py" $args[0]
exit $LASTEXITCODE
