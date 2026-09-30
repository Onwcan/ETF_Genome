$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if ($args.Count -ne 1) { throw "Usage: .\scripts\build_shock_graph.ps1 YYYY-MM-DD" }
& (Join-Path $Root ".venv\Scripts\python.exe") "scripts\build_shock_graph.py" $args[0]
exit $LASTEXITCODE
