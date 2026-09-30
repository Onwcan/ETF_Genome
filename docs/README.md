# ETF Genome documentation

The [project README](../README.md) introduces the hybrid Python/C++ platform and its quick start. This index points to each topic's primary home; future development is consolidated in one roadmap.

## Start here

- [Architecture](ARCHITECTURE.md) explains system-wide ownership, data flow, and artifact boundaries.
- [Project status](PROJECT_STATUS.md) records current capabilities, implementation limits, and environment constraints.
- [Roadmap](ROADMAP.md) organizes future work by status and engineering workstream.
- [Validation](VALIDATION.md) records remote CI evidence and reproducible local checks.

## Data and research

- [Data model](DATA_MODEL.md) defines holdings identity, units, storage, concentration, and drift semantics.
- [Market data](MARKET_DATA.md) explains daily prices, adjustment provenance, synchronization, and risk inputs.
- [Free data providers](FREE_DATA_PROVIDERS.md) distinguishes provider roles, authentication, and access/redistribution boundaries.
- [Shock graph](SHOCK_GRAPH.md) describes publication-aware graph analytics and mechanical direct shock scenarios.
- [Graph data model](GRAPH_DATA_MODEL.md) defines ETF/security nodes, edges, manifests, and snapshot availability.

## Machine learning

- [Experiment tracking](EXPERIMENT_TRACKING.md) explains optional W&B logs and local MLflow runs/artifacts.
- [Optuna](OPTUNA.md) describes reproducible studies, resume rules, and train/validation-only tuning.
- [Model lifecycle](MODEL_LIFECYCLE.md) explains candidate registration, production selection, and explicit promotion.

## Native C++

- [Native developer guide](../native/README.md) provides builds, CLI examples, snapshots, feeds, and benchmark commands.
- [Native architecture](NATIVE_ARCHITECTURE.md) explains networking, queue ownership, sparse state, and shutdown.
- [Binary formats](BINARY_PROTOCOL.md) specifies the event wire protocol and validated graph snapshot format.
- [Native performance](NATIVE_PERFORMANCE.md) records local synthetic measurements, timing scopes, and limitations.

## Orchestration

- [Orchestration architecture](ORCHESTRATION_ARCHITECTURE.md) separates research data/ML workflows from the desktop runtime.
- [Airflow](AIRFLOW.md) describes data DAG definitions, isolated setup, and scheduler validation boundaries.
- [Kubeflow](KUBEFLOW.md) describes training pipeline definitions, compilation, and container/cluster requirements.

## Desktop and operations

- [Background updates](BACKGROUND_UPDATES.md) explains cache-first startup, refresh eligibility, backoff, and cancellation.
- [Windows packaging](WINDOWS_PACKAGING.md) provides the local build recipe and release verification limits.
- [DuckDB on Windows](DUCKDB_WINDOWS.md) explains an observed native-library policy block and the analytical fallback.

## Research environment

- [Graph research environment](GRAPH_RESEARCH_ENVIRONMENT.md) explains isolated Linux/WSL PyTorch setup and the desktop dependency boundary.

Contribution and security policies are in [CONTRIBUTING.md](../CONTRIBUTING.md) and [SECURITY.md](../SECURITY.md).
