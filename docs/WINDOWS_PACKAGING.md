# Windows packaging

The repository supplies a PyInstaller specification for a Windows desktop build.
It does not include a prebuilt executable, a signed release, or an installer.
Build and smoke-test the application on the Windows machine that will produce it.

See [Architecture](ARCHITECTURE.md) for the Python desktop boundary, [Model Lifecycle](MODEL_LIFECYCLE.md) for model selection, and [DuckDB on Windows](DUCKDB_WINDOWS.md) for an observed native-library constraint.

## Build from source

From the repository root with Python 3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,ml,packaging]"
.\scripts\build_windows.ps1
```

The `ml` extra is needed for the XGBoost package and native library collected by
the specification. The equivalent direct build command is:

```powershell
.\.venv\Scripts\pyinstaller.exe packaging\windows\ETFGenome.spec --noconfirm --clean --distpath dist --workpath build
```

The output is `dist\ETFGenome\ETFGenome.exe`. Distribute the entire
`dist\ETFGenome` directory; the executable depends on the adjacent bundled files.
The default build has no console window. To build a developer copy with a console,
run `scripts\build_windows_debug.ps1`, which sets
`ETF_GENOME_PYINSTALLER_CONSOLE=1` for the build. Both helpers write to the same
output directory.

## What the specification bundles

The specification collects the desktop runtime, Polars, DuckDB when its native
library can be loaded, and XGBoost with its Windows DLL. If DuckDB cannot load,
the application has a Polars fallback for its holdings summaries.

It excludes scikit-learn, PyTorch, TensorFlow, Airflow, Kubeflow, Optuna, MLflow,
and Weights & Biases from the executable. The desktop scores saved artifacts;
it does not run training or start orchestration services.

The synthetic `tests/fixtures/sample_holdings.json` file is bundled for the
vertical slice. Model artifacts are optional: the specification includes
`models/risk_baseline`, `models/registry/registry.json`, and `models/production`
only when those paths exist locally. The public source checkout supplies no
trained models, downloaded filings, market history, credentials, or local logs.
Review locally generated model files and metadata before distributing a build
that bundles them.

The application writes its cache, Parquet files, SQLite catalog, and logs under
`%LOCALAPPDATA%\ETFGenome`, unless `ETF_GENOME_DATA_DIR` overrides that location.
An empty data directory shows missing-data status until the user configures and
runs synchronization. Missing trained models produce unavailable risk estimates.

## Offline startup smoke test

This test uses a fresh temporary data directory and avoids live data requests.
It checks startup and shutdown, rather than model quality or live synchronization.

```powershell
$smokeDataDir = Join-Path $env:TEMP ("etf-genome-smoke-" + [guid]::NewGuid())
$env:ETF_GENOME_DATA_DIR = $smokeDataDir
$env:ETF_GENOME_OFFLINE_MODE = "true"
$env:ETF_GENOME_DESKTOP_SMOKE = "1"
$env:QT_QPA_PLATFORM = "offscreen"
try {
    $smokeProcess = Start-Process -FilePath ".\dist\ETFGenome\ETFGenome.exe" -WindowStyle Hidden -Wait -PassThru
    if ($smokeProcess.ExitCode -ne 0) {
        throw "Desktop smoke test failed with exit code $($smokeProcess.ExitCode)"
    }
} finally {
    Remove-Item Env:ETF_GENOME_DATA_DIR, Env:ETF_GENOME_OFFLINE_MODE, Env:ETF_GENOME_DESKTOP_SMOKE, Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
}
```

Inspect the local log under `$smokeDataDir\logs` when startup fails. Build outputs
and temporary application data are ignored by Git.

## Release validation boundary

The build recipe and smoke test do not establish a signed, installable release
or fresh-machine compatibility. Those milestones are tracked in the
[Windows release roadmap](ROADMAP.md#windows-release-preparation).
Package size and startup time depend on the installed dependencies and bundled
model artifacts; measure the produced build before making release claims.
