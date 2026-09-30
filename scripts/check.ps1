$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Python environment not found. From the project root run: py -3.12 -m venv .venv"
}
& $Python -m ruff check src tests apps scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m ruff format --check src tests apps scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m mypy
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python scripts/check_publication.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pytest
exit $LASTEXITCODE
