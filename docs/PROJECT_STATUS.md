# Project status

This document describes the source distributed in this repository. Prior development notes refer to local runs and artifacts; those outputs are not a fresh-clone guarantee. The repository publishes source and synthetic fixtures, not downloaded datasets, trained models, executables, or private research logs.

## Implemented source

| Component | Scope | Evidence in the tree |
| --- | --- | --- |
| Holdings analytics | Normalization, stable identifiers, concentration, exposures, mandate drift | `data/normalization`, `genome`, `drift`, offline vertical-slice tests |
| Local storage | Parquet snapshots, SQLite catalog, DuckDB with Polars fallback | `data/storage`, storage tests |
| SEC ingestion | QQQ filing discovery, defensive XML parsing, caching, bounded retry and sync policy | `data/sources`, `data/ingestion`, parser and ingestion tests |
| Desktop | Cached QQQ overview, background refresh, status display, local risk inference | `desktop`, `services`, desktop tests, PyInstaller spec |
| Daily market data | QQQ sync, canonical provider schema, provenance and adjustment mode | Market provider and feature tests |
| Risk baseline | Point-in-time holdings joins, forward risk targets, chronological splits, explicit training | `features/risk`, `training`, point-in-time and model tests |
| Experiment lifecycle | Optuna, optional MLflow/W&B tracking, versioned candidates and explicit promotion | `experiments`, lifecycle scripts and tests |
| Orchestration | Airflow DAG and Kubeflow pipeline definitions, local smoke interfaces | `orchestration`, orchestration tests |
| Holdings graph | SEC-resolved fund universe, publication-aware snapshot, overlap, crowding, direct shocks | `graph`, graph tests and scripts |
| Structural embedding | Optional PyTorch link-reconstruction research baseline | `research/graph/baseline.py` |
| Native component | C++20 signed direct exposure, incremental price state, binary protocol/snapshot, bounded SPSC, Linux synthetic TCP/epoll feed, component benchmarks | `native`, CTest cases, Python CSV exporter |

The evidence column identifies code and test locations; it does not assert that all optional integrations or research runs have executed. The README provides commands to reproduce the offline checks.

## Runtime and research boundary

The Windows desktop reads a local cache and existing model artifacts. It does not start training, an orchestration cluster, a model server, or a C++ process. PyTorch, PyG, CUDA, WSL2, Airflow, and Kubeflow are not required to open it.

Training needs your own permitted price history and suitable runtime dependencies. Model inference needs compatible artifacts produced by the explicit training workflow. Graph scenarios need locally ingested filings and a chosen as-of date. Graph universe size and coverage depend on actual SEC resolution and cached data; no previously reported local node counts are promised by a fresh checkout.

The native replay and Linux loopback feed use generated events. The shock CLI calculates direct exposure from a static CSV or validated binary snapshot. Price updates maintain reference-relative returns through a sparse reverse index. Measured local component results and their scope are recorded in [NATIVE_PERFORMANCE.md](NATIVE_PERFORMANCE.md). They do not establish exchange latency, deployment suitability, or trading profitability.

## Verification boundaries

- Ordinary pytest uses synthetic fixtures, temporary storage, and fake network transports. The two live integrations are opt-in.
- Ruff and mypy cover the Python source configured in `pyproject.toml`; CTest checks the native component separately.
- Formatter and publication checks support repository hygiene. Optional Python/native parity checks use an explicitly configured binary; GitHub Actions definitions do not imply that a remote CI run has passed.
- Dependency groups and reproducible commands are supplied. Optional model training, SEC access, market-provider access, GPU operation, and cluster execution require separate verification in the target environment.
- PyInstaller configuration and build helpers are present; compiled executables are generated locally.
- Airflow and Kubeflow definitions do not establish a deployed scheduler or successful Kubernetes execution.
- The structural embedding baseline's presence does not establish a trained or evaluated graph model.

## Future work

Phase 8 now provides the native C++ market-data and systems foundation. Phase 9 is native performance engineering, Linux profiling, and memory optimization. Phase 10 is Python/C++ integration with pybind11. Both remain future work. The temporal research proposal is retained as [Phase 11](PHASE11_ROADMAP.md), with the [original Phase 8 document](PHASE8_ROADMAP.md) preserved historically. No temporal model was implemented or trained in this phase.

Additional serving, monitoring, graph visualization, and larger fund universes remain separate future work. Historical documents such as `ARCHITECTURE.md` and `ROADMAP.md` describe earlier project stages; this status document and the README summarize the current source.
