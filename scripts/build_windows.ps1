$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyInstaller)) {
    throw "PyInstaller not found. Install the packaging extra in .venv first."
}
& $PyInstaller "packaging\windows\ETFGenome.spec" --noconfirm --clean
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Built dist\ETFGenome\ETFGenome.exe"
