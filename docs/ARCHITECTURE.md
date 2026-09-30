# Architecture

> Historical Phase 1 design notes. The separation between desktop runtime and
> research infrastructure still applies, but feature descriptions and planned
> extension points below predate the later market-data, risk-model, orchestration,
> shock-graph, and native C++ work. See [Project status](PROJECT_STATUS.md) for the
> current implementation and [Phase 11 roadmap](PHASE11_ROADMAP.md) for temporal research.

ETF Genome separates the code a Windows user will eventually run from the infrastructure used to research and train models.

## Standalone Windows runtime

The runtime is the Phase 1 library in `src/etf_genome` plus the PySide6 shell in `src/etf_genome/desktop`. `apps/desktop/main.py` is the process entry point used by developers and by PyInstaller.

That process:

- reads configuration from environment variables and optional `.env`
- normalizes holdings with Polars
- stores Parquet files and a SQLite catalog on the local disk
- runs DuckDB queries in-process when the native library loads. If Windows application control blocks that library, the same snapshot aggregation is computed with Polars and the result records `analytics_engine=polars_fallback`
- calculates concentration and mandate drift in-process
- renders a desktop window from cached holdings before any network call
- refreshes SEC NPORT-P filings for QQQ on a background thread through `UpdateCoordinator`

It does not start a web server. It does not require Docker, Kubernetes, Airflow, Kubeflow, R, Scala, W&B, MLflow, Grafana, or a database server. A future production executable must keep that property. If a later feature needs a local HTTP API, the executable has to start and stop that API itself. Phase 1 does not add one, because the calculations are ordinary Python function calls.

Dependency groups in `pyproject.toml` exist so a desktop environment does not have to install training tools:

| Group | Phase 1 role |
| --- | --- |
| core (`project.dependencies`) | Runtime analysis: Pydantic, Polars, PyArrow, NumPy, DuckDB, httpx, defusedxml |
| `data` | Names the same analytical libraries for a data-only install. New connectors that the desktop app does not need should be added here rather than to core. |
| `desktop` | PySide6 |
| `dev` | pytest, Ruff, mypy |
| `packaging` | PyInstaller |
| `ml` | scikit-learn and XGBoost, not imported by Phase 1 |
| `research` | W&B and MLflow, not installed for the Phase 1 checks |
| `training` | Optuna only. Airflow and Kubeflow stay outside the Python package. |

Polars is in the core list because the end-user application itself normalizes holdings and builds features. It is not reserved for a server-side job.

## Training and research infrastructure

These locations are extension points. Phase 1 does not run them.

| Location | Future responsibility |
| --- | --- |
| `pipelines/airflow` | SEC ingestion, market-data refresh, FRED refresh, validation, feature refresh |
| `pipelines/kubeflow` | Dataset build, training, tuning, evaluation, registration |
| `research/python` | Experiments that may use W&B |
| `research/r` | Statistical checks and research reports |
| `scala` | High-volume transforms or graph-edge aggregation if Polars is no longer enough |
| `src/etf_genome/models` | Training code, kept out of the desktop import graph |
| `src/etf_genome/serving` | Later BentoML and FastAPI services |
| `src/etf_genome/monitoring` | Later Evidently reports and Grafana metrics |
| `src/etf_genome/risk` | Later supervised risk models |
| `src/etf_genome/graph` | Later shock-graph features |

A model that is eventually shipped inside the executable should be an exported artifact loaded by the runtime, not a dependency on the system that trained it. Kubeflow can train a model. The `.exe` should load a file. The same rule applies to R and Scala: they may produce validated numbers or datasets during research, and the desktop app should read the resulting Parquet or model file.

## Module boundaries

```text
apps/desktop/main.py
    -> desktop.runner
        -> services.phase1.run_vertical_slice
            -> normalization
            -> LocalHoldingsStore
            -> genome report
            -> drift report
        -> desktop.summary
        -> desktop.window
```

The window receives a `DesktopSummary` that is already formatted. Button handlers are not where holdings math belongs; the proof-of-concept window has no buttons.

External IO sits behind small interfaces:

- SEC HTTP goes through `HttpTransport`. Tests pass a fake transport.
- Market prices have a `MarketDataProvider` protocol and no vendor implementation yet.
- Storage is split into Parquet files, a SQLite catalog, and a DuckDB query helper. `LocalHoldingsStore` is the facade the service calls.

Feature code does not open sockets and does not import PySide6. The desktop package does not recompute HHI or drift.

## Data flow

```text
raw rows or the synthetic fixture
    -> normalize_holdings (Polars)
    -> canonical snapshot frame
    -> Parquet + SQLite index
    -> read back
    -> DuckDB count check
    -> concentration, sector, country
    -> DriftReport
```

The vertical slice calculates the genome and drift reports from the frames read back out of Parquet. A result that never touched disk is not treated as success.

## Identifiers and time

Funds are keyed by `fund_id`. A ticker is a display attribute. If a caller has no `fund_id`, the normalizer can derive one from CIK plus series id. It will not use a ticker as a fund key.

Holdings prefer CUSIP, then ISIN, then security ticker, then a normalized name. A name key is a last resort and is not stable across filings.

`snapshot_date` is the portfolio as-of date supplied by the source. `source_timestamp` is stored as a UTC timestamp. Windows Python needs the `tzdata` package, which is a core dependency, so `zoneinfo` can resolve that zone. The field records when the source says the observation was produced or filed. Phase 1 does not invent a filing lag. Later training code must not build a label from data dated after the decision point, and it must not randomly split financial time series. That evaluation design is Phase 2 work; the storage layout already keeps each snapshot under its own date so a later split can be done by date.

## Shock graph, later

The canonical holdings table is already an ETF-to-security edge list: `fund_id`, `security_id`, `snapshot_date`, `portfolio_weight`. Sector, industry, and country are attributes on those edges. A later graph builder can read the Parquet files. Phase 1 does not construct a graph object and does not train a GNN.

## Logging and configuration

`configure_logging` writes a console line and a rotating JSON file under the configured log directory. A formatter redacts common credential patterns. The SEC user agent is not written at info level.

`AppSettings` is a Pydantic settings model. Prefix: `ETF_GENOME_`. Nested flags use a double underscore, for example `ETF_GENOME_FEATURE_FLAGS__LIVE_SEC_FETCH`.

## What was intentionally left out of the runtime

- No global mutable configuration object beyond the logger handlers.
- No PostgreSQL or other database server.
- No Flask.
- No TensorFlow or Keras copy of a model.
- No Scala or R process spawned by the desktop app.
- No live download of the historical N-PORT archive.
