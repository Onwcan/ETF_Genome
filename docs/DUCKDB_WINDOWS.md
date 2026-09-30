# DuckDB on this Windows machine

The DuckDB package is installed and its extension file is present:

```text
.venv\Lib\site-packages\_duckdb.cp312-win_amd64.pyd
```

Importing it fails before PyInstaller is involved:

```text
ImportError: DLL load failed while importing _duckdb:
Uygulama Denetimi ilkesi bu dosyayı engelledi.
```

That message is Windows application control (the policy that blocks a binary). Polars 1.44.2 imports successfully in the same environment, so this is not a general failure to load native code, not a missing Visual C++ runtime message, and not a PyInstaller extraction problem.

The frozen build logs the same import failure while collecting DuckDB. The executable keeps the Polars summary fallback. `analytics_engine` is `polars_fallback` when DuckDB cannot load and `duckdb` when it can.

No packaging change can make a policy-blocked DLL load, and this project does not ask for application control to be disabled. DuckDB remains the analytical path whenever the import succeeds.
