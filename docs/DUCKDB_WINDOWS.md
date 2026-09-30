# DuckDB on Windows

DuckDB provides analytical SQL over local holdings Parquet files. A native Windows development environment previously blocked its extension through Application Control, while Polars could still load. This is an observed environment-specific constraint, not a claim that DuckDB fails on every Windows installation.

The observed error occurred during a direct DuckDB import, before PyInstaller packaging:

```text
ImportError: DLL load failed while importing _duckdb:
Uygulama Denetimi ilkesi bu dosyayı engelledi.
```

## Implemented fallback

`LocalHoldingsStore.summarize` probes the DuckDB import. If it succeeds, the summary uses DuckDB and reports `analytics_engine=duckdb`. If the import fails, the holdings count and weight-sum summary uses Polars and reports `analytics_engine=polars_fallback`.

The fallback covers that holdings summary, not arbitrary DuckDB SQL. The application logs the original import error. A missing package or another import failure should be diagnosed from the actual target environment rather than assumed to have the same policy cause.

The PyInstaller specification attempts to collect DuckDB when its native library can load. A build made in a constrained environment therefore needs the same target-machine verification as any other native dependency. See [Windows Packaging](WINDOWS_PACKAGING.md) for build and smoke commands and [Validation](VALIDATION.md) for recorded evidence.

No security-policy change is part of ETF Genome setup. Use the supported summary fallback when DuckDB cannot load, and verify direct imports and the packaged application in the intended release environment.
