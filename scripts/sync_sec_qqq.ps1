$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Python environment not found. From the project root run: py -3.12 -m venv .venv"
}
& $Python "scripts\sync_real_qqq.py"
exit $LASTEXITCODE
