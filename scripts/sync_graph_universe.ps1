$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
& (Join-Path $Root ".venv\Scripts\python.exe") "scripts\sync_graph_universe.py"
exit $LASTEXITCODE
