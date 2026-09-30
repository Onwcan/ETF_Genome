$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyInstaller)) {
    throw "PyInstaller not found. Install the packaging extra in .venv first."
}
$env:ETF_GENOME_PYINSTALLER_CONSOLE = "1"
& $PyInstaller "packaging\windows\ETFGenome.spec" --noconfirm --clean
$code = $LASTEXITCODE
Remove-Item Env:ETF_GENOME_PYINSTALLER_CONSOLE -ErrorAction SilentlyContinue
if ($code -ne 0) { exit $code }
Write-Output "Built a console developer copy at dist\ETFGenome\ETFGenome.exe"
