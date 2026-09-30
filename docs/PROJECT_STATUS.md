# Project status

ETF Genome currently combines a publication-aware Python ETF analysis/research application with a C++20 synthetic market-data and exposure runtime. This document records current implementation and verification limits; future priorities belong in the [roadmap](ROADMAP.md).

The public repository supplies source, configuration templates, and synthetic fixtures. A fresh checkout does not include downloaded filings, market histories, trained models, executables, or private research logs.

## Data layer

| Capability | Current state |
| --- | --- |
| SEC N-PORT | Filing discovery, defensive XML parsing, normalization, caching, retry/backoff, and incremental QQQ/graph-universe ingestion are implemented |
| Holdings storage | Canonical Parquet snapshots and SQLite fund/filing/snapshot provenance are implemented |
| Analytics | Concentration, signed exposure summaries, largest positions, and mandate drift are implemented; DuckDB summaries have a Polars fallback |
| Point-in-time availability | Risk joins and graph snapshots use SEC publication dates, distinct from portfolio report/retrieval dates |
| Market data | Twelve Data is the authoritative QQQ daily workflow; Tiingo, Massive, Alpha Vantage, and Yahoo comparison adapters exist without automatic failover |
| Macro data | The FRED provider protocol exists; FRED/ALFRED ingestion and revision-aware features are not implemented |

Provider credentials, current access terms, available history, and permitted use must be supplied/checked in the target environment. Adapter tests use fake transports; their passing results do not certify current live-provider behavior. Missing classifications and unresolved identities remain explicit.

## Risk research and model lifecycle

- QQQ market/holdings features, forward 20-session volatility/drawdown targets, chronological splits, leakage checks, and XGBoost baseline training are implemented.
- Optuna studies resume from local SQLite storage and tune against train/validation data; frozen candidate training evaluates the untouched test split.
- W&B is optional and supports offline use. MLflow records local SQLite runs and artifacts; its integration test performs real local logging and lookup.
- The local file-based registry tracks experiments, candidates, production models, and archived models. Promotion is an explicit command with compatibility/metric checks.
- Desktop inference loads a compatible production artifact or existing local baseline fallback. It does not train, tune, or automatically promote models.

Training requires permitted local price history and compatible dependencies. No universal model-quality, trading-profitability, or pretrained-model claim follows from the existence of these workflows. See [model lifecycle](MODEL_LIFECYCLE.md) and [experiment tracking](EXPERIMENT_TRACKING.md).

## Graph analytics

Implemented graph services resolve the configured fund universe against official SEC identities and build static publication-aware ETF-security snapshots. They calculate portfolio overlap, cosine/Jaccard similarity, security crowding, degree measures, and signed direct shock exposure.

Universe size and coverage depend on actual identity resolution and cached filings. Unresolved/ambiguous funds and unsupported classifications are reported. Canonical holdings preserve missing weights, but graph aggregation currently uses Polars sum: an all-null weight group can become `0.0`, so graph missing-weight counts can understate unavailable source weights. Direct shock is a mechanical holdings calculation, without learned secondary propagation or a causal contagion interpretation.

`research/graph/baseline.py` contains a structural link-reconstruction embedding scaffold. Native Windows PyTorch training was blocked by Windows Application Control, so no successfully trained/evaluated graph model is claimed. Temporal graph states/datasets, sequence models, and a temporal GNN are not implemented. See [shock graph](SHOCK_GRAPH.md) and [research environment](GRAPH_RESEARCH_ENVIRONMENT.md).

## Native C++20

| Component | Current state |
| --- | --- |
| Portable analytical core | Signed/missing-weight direct shocks, immutable sparse graph, CSV parsing, and scalar-reference checks |
| Protocol and concurrency | Fixed-width big-endian EGMD frames, bounded incremental decoder, sequence counters, and bounded SPSC with explicit ownership |
| Linux transport | Synthetic localhost nonblocking TCP/epoll server/client, stop-aware backpressure, optional affinity, and orderly worker cleanup |
| Exposure runtime | Consumer-owned persistent reference prices/returns and sparse affected-fund updates |
| Snapshots | Versioned binary graph save/load with size, bounds, checksum, and structural validation |
| Measurement | Separate SPSC/decoder/exposure/TCP benchmarks, latency histograms, allocation-scope checks, and environment metadata |

Portable code is verified with GCC, Clang, and MSVC; Linux networking is excluded from Windows builds. Native processing runs as separate executables and is not part of the desktop import/process graph. The current Python/C++ boundary is CSV export plus native binary snapshot compilation; pybind11 integration is absent.

Known runtime limits include external instrument/tick mapping, no reconnect or session recovery, framing-only EOF validation, approximate histogram quantiles, and possible accumulated floating-point rounding. Local synthetic benchmarks and their exact scope are recorded in [native performance](NATIVE_PERFORMANCE.md); they do not establish exchange latency.

## Desktop

The PySide6 desktop displays cached QQQ holdings, freshness/status, background refresh results, and local risk estimates. Offline mode and provider failures preserve existing cache contents. Empty caches and missing models produce explicit unavailable status.

PyInstaller specifications and PowerShell helpers exist for a local Windows `onedir` build. The desktop requires neither WSL2/PyTorch/CUDA nor orchestration/tracking services. No prebuilt executable, signed release, installer, auto-update mechanism, or fresh-machine release certification is distributed. See [Windows packaging](WINDOWS_PACKAGING.md).

## Orchestration

Airflow data DAG definitions and Kubeflow training pipeline definitions are implemented under `orchestration/`. Reusable tasks, manifests, definition checks, and smoke interfaces exist. These establish a foundation, not a deployed scheduler or successful container/Kubernetes training run.

The desktop refresh coordinator operates independently. Orchestrated training ends at a candidate and does not promote automatically. Container builds, cluster execution, shared artifact storage, and live scheduled ingestion require separate target-environment verification. See [orchestration architecture](ORCHESTRATION_ARCHITECTURE.md).

## CI and validation

The verified remote baseline is green for Python on Ubuntu and Windows, publication validation, native GCC/Clang/MSVC, ASan/UBSan, TSan, and Python/C++ parity on Linux and Windows. Evidence links and exact validation boundaries are maintained in [VALIDATION.md](VALIDATION.md).

Ordinary pytest uses synthetic fixtures, local temporary storage, and fake network transports. Live SEC/market integrations are opt-in. CTest validates the native subsystem separately; optional Python/native tests use an explicitly configured executable. CI correctness checks and local benchmark measurements have different purposes and environments.

## Known environment constraints

Windows Application Control blocked specific native libraries during earlier local checks, including PyTorch and DuckDB. These are environment-specific observations, not a statement that all Windows installations fail. The desktop has a DuckDB-to-Polars fallback. Deep-learning research should use an isolated Linux/WSL environment without weakening Windows security policy.

Local WSL benchmark timings reflect scheduling, power, thermal, and virtualization variability. Airflow/Kubeflow runtime deployments, live-provider access, GPU operation, and release signing are not certified by the green offline CI matrix.

## Not implemented

Temporal graph learning, learned secondary shock propagation, in-process Python/C++ bindings, reconnect/session recovery, model-serving and drift-monitoring services, a desktop graph/stress explorer, and large-scale bulk N-PORT ingestion are absent. `serving` and `monitoring` remain package placeholders.

Real exchange/broker connectivity, order routing, buy/sell signals, investment recommendations, profitability claims, causal contagion claims, mandatory paid infrastructure, and automatic model promotion are outside the current project scope.
