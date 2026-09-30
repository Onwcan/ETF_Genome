# ETF Genome roadmap

This is the single authoritative development roadmap. [Project status](PROJECT_STATUS.md) owns current implementation facts, [architecture](ARCHITECTURE.md) owns system design, and [validation](VALIDATION.md) owns verification evidence.

Status describes the workstream, not a percentage or delivery date:

| Status | Meaning |
| --- | --- |
| COMPLETE | The foundation exists with the verification limits stated below |
| CURRENT | The next engineering focus; planned profiling/optimization is not yet implemented |
| PLANNED | An intended workstream with prerequisites and completion criteria |
| EXPLORATORY | A direction requiring a demonstrated problem and feasibility evidence |
| DEFERRED | Deliberately postponed until prerequisites justify it |

## Guiding principles

- Correctness precedes optimization; point-in-time correctness precedes model complexity.
- Performance claims require reproducible measurements and explicit timing boundaries.
- Python owns data, research, ML, graph construction, and the desktop; C++20 owns performance-sensitive native event processing.
- Preserve publication dates, identifier provenance, signed/missing weights, and provider adjustment semantics.
- Keep the desktop cache-first and usable without research services, WSL2, or GPU libraries.
- Keep the core data path free of mandatory paid data or hosted infrastructure.
- Promote production models explicitly, after compatible artifacts and evaluation evidence are reviewed.

Use Polars where practical, Parquet for analytical data, SQLite for local metadata, and XGBoost for current tabular risk models. Optuna, optional W&B, local MLflow, Airflow, and Kubeflow have distinct responsibilities. PyTorch is the intended deep-learning research framework. A named tool is adopted only when it solves the measured problem.

## Current architecture

Publication-aware holdings and daily market data feed Python analytics, risk datasets, and static ETF-security graphs. Model files cross the training-to-desktop boundary. Explicit CSV export crosses the Python-to-native boundary; the native CLI can compile a binary graph snapshot. Separate C++ executables process a synthetic localhost feed through decoder, SPSC, and sparse exposure state. See [architecture](ARCHITECTURE.md) for the full design.

## Completed foundations

**COMPLETE** denotes implemented source and exercised foundations, not a production trading system or a guarantee of optional external deployment.

| Workstream | Established foundation | Verification boundary |
| --- | --- | --- |
| Public data | SEC N-PORT discovery/parsing, identifier normalization, publication-aware holdings, local provenance, Parquet/SQLite | Live provider access and historical coverage depend on local credentials/data |
| Point-in-time analytics | Concentration, drift, market/holdings risk datasets, chronological splits, leakage checks | Missing information is explicit; no invented classifications or returns |
| Risk research and model lifecycle | XGBoost baseline, Optuna studies, optional/offline W&B, local MLflow, candidates and explicit promotion | No pretrained model or universal forecasting-quality claim |
| ETF-security graph | Multi-ETF snapshots, overlap, crowding, signed direct shocks | Mechanical direct exposure; learned embeddings/propagation are not validated models |
| Orchestration foundation | Airflow data DAGs, KFP training definitions, manifests and dependency isolation | Definitions/compilation do not establish scheduler, container, or cluster execution |
| Desktop foundation | Cached QQQ views, background refresh, local inference, Windows build recipe | No signed installer or fresh-machine release certification |
| Native systems | C++20, binary protocol/decoder, Linux nonblocking TCP/epoll, bounded SPSC, sparse exposure, binary snapshots, benchmarks | Synthetic/local transport; no exchange connection or session recovery |
| Validation | Cross-platform Python/native CI, parity, sanitizers, publication guard | Correctness evidence is distinct from local benchmark evidence |

## Current engineering focus

### Native performance engineering

**CURRENT.** Establish measurement-driven profiling before changing hot paths or adding bindings. The existing [local synthetic benchmark](NATIVE_PERFORMANCE.md) is the comparison baseline; new claims must use repeated uninstrumented Release runs and retain their raw evidence.

Planned investigations:

- Linux `perf` profiles and counters to locate CPU time, cache misses, and branch behavior.
- Tail-latency analysis that separates clocks, scheduling, queue waits, transport, and exposure processing.
- False-sharing experiments and CPU-affinity comparisons, including denied/unsupported pinning behavior.
- Allocator/preallocation analysis with named scopes rather than process-wide zero-allocation assumptions.
- Syscall analysis, send/receive batching, and queue notification comparisons.
- Optional busy-poll experiments only when latency, CPU use, fairness, and shutdown tradeoffs are reported.
- Reproducibility records for graph size, event count, compiler/flags, CPU topology, load, warmup, histograms, and variability.

Completion requires a repeatable profile, a stated bottleneck, before/after data with unchanged workload/measurement boundaries, preserved numerical parity, and passing relevant sanitizer/correctness checks. A slower or neutral result is a valid result; speculative rewrites are not evidence.

## Near-term work

### Python/C++ integration

**PLANNED, after native profiling.** Evaluate pybind11 for selected native analytics/runtime components.

- Define a small API and choose operations whose end-to-end cost justifies a native boundary.
- Preserve graph/workspace ownership and lifetimes; avoid unnecessary large dataset copies with explicit safe buffer contracts.
- Specify exception translation, cancellation, threading, and Python GIL behavior.
- Keep C++ independent of Python internals and usable as a standalone library/executable.
- Preserve signed/missing-weight semantics and numerical parity across bindings and CLI paths.
- Keep native integration optional for the desktop until packaging and target-machine support are verified.

Completion requires documented ownership, input validation, lifetime/exception tests, parity, portable builds, and end-to-end measurements including crossing/copy costs. No binding exists today.

### Native reliability

**PLANNED.** Harden the synthetic/local runtime with explicit application-session semantics.

- Reconnect policy, bounded retry/backoff, and cancellation during recovery.
- Session recovery, SnapshotStart/SnapshotEnd validation, and a defined resynchronization boundary.
- Sequence gap/duplicate/out-of-order policy that distinguishes observation from recovery.
- Explicit backpressure modes, counters, and documented accepted/unprocessed event behavior.
- More useful session/error observability without per-event hot-path logging.
- A graph identity/tick-unit handshake or equivalent validated mapping contract.

Completion requires deterministic disconnect/reconnect, malformed-session, sequence-recovery, slow-consumer, and stop/drain tests. The default scope remains synthetic localhost; real exchange semantics are not implied.

## Medium-term work

### Temporal shock graph research

**PLANNED research, not implemented forecasting.** Compare next-session ETF response estimates against direct holdings exposure and simpler temporal baselines. A learned association must not be presented as causal contagion, profitability, or an execution signal.

#### Research environment and artifact boundary

Use an isolated Python 3.12 Linux/WSL environment for PyTorch research. Native Windows PyTorch was blocked by Windows Application Control during local validation; security policy must not be weakened to run this work. The Windows desktop remains independent of PyTorch, PyG, CUDA, and WSL.

Validate a CPU tensor operation and tiny training smoke test first. CUDA is optional and cannot be required for correctness. Evaluate PyTorch Geometric only after PyTorch works; a pure PyTorch message-passing encoder with GRU is a fallback. Environment setup and diagnostics belong in [graph research environment](GRAPH_RESEARCH_ENVIRONMENT.md).

Keep research environments and optional copied training caches on the Linux filesystem. Canonical source datasets remain authoritative. Copies must carry source fingerprints and copy metadata; discover paths at runtime. Exchange validated datasets/model artifacts explicitly rather than loading arbitrary WSL paths into the desktop.

#### Selective underlying-security prices

- Preserve the configured graph universe initially and resolve funds against official identities; never invent SEC series ids or tickers.
- Start with approximately 150–200 price-eligible securities under a configurable cap.
- Rank selection deterministically using documented degree, aggregate absolute weight, maximum weight, and reference-fund coverage criteria.
- Report signed/absolute exposure coverage, minimum/median ETF coverage, exclusions, and missing histories.
- Calculate provider request budgets before download; respect current limits and implement incremental resumable cache synchronization.
- Retain provider, adjustment, request-range, and source provenance. Optional secondary series stay separate; no silent substitution or mandatory paid subscription.

#### Dynamic point-in-time graph states and temporal features

Graph states become valid when filings are public. Record validity intervals, source accessions, and graph fingerprints; report dates cannot expose unpublished holdings. Test graph-state transitions and prevent future holdings from entering earlier samples.

Build trailing security returns/volatility/shock measures, ETF features, and observed coverage. Sequences must align their input window with the next-session target, handle state changes, warmup, missing dates, and low-coverage exclusion by a documented rule.

Fix chronological train, validation, and final-test ranges before training. Target windows must not cross split boundaries. Fit scaling, thresholds, feature selection, and architecture choices using training/validation only; the final test must not set training length or model design.

Fingerprint universe membership, graph states, price provenance, feature/target versions, sequence configuration, and split configuration. A file path is not dataset identity.

#### Baselines, sequence models, and temporal GNN

Establish the comparison ladder before increasing complexity:

1. Zero-response and direct mechanical exposure baselines where mathematically comparable.
2. Non-graph tabular/neural baselines.
3. A temporal sequence baseline.
4. Verified PyTorch graph representation experiments.
5. A modest graph encoder plus GRU or another justified temporal GNN.

Train one stable model before a small optional tuning study. The existing structural link-reconstruction scaffold is neither a temporal model nor evidence of successful graph training.

#### Out-of-time evaluation and case study

Report validation and untouched final-test MAE, RMSE, R², and descriptive correlation separately. Include pooled and selected per-ETF results with QQQ shown separately. Define large-shock subsets before final evaluation and report sample sizes. Directional accuracy, if shown, is a secondary diagnostic, not trading accuracy.

Select a QQQ test-period case using a deterministic rule independent of favorable model performance. Show the public graph state, major security moves, covered exposure, direct approximation, observed response, and model estimate, with unsupported cases left unavailable.

#### Tracking and artifact contract

Outputs must include model state, feature/graph schemas, price-universe manifest, target, sequence length, date ranges, seeds, software/device versions, fingerprints, and split-specific metrics. A controlled export verifies compatibility with the receiving project.

Tracking defaults to disabled or offline. Do not upload raw filings or market histories. A temporal model remains an experiment or candidate and is never automatically promoted to desktop production.

#### Research completion criteria

1. Existing Python/offline regression checks pass without PyTorch, WSL, or CUDA.
2. Linux Python/PyTorch CPU operations and tiny learning/serialization tests pass; optional CUDA/PyG status is recorded factually.
3. Selection, request budgeting, cache resume, provenance, and coverage are reproducible.
4. Graph-state tests prove publication-date transitions and no future holdings.
5. Temporal tests cover lookback, next-session alignment, split isolation, missing dates, and changing states.
6. Synthetic tests validate message passing, output shapes, learning on trivial data, and artifact round trips.
7. Baselines and temporal training produce separate validation and untouched final-test reports.
8. Subset metrics and the deterministic case study appear only when supported by data.
9. Exported fingerprints/compatibility are verified and research libraries stay outside the desktop runtime.

### Serving and monitoring

**PLANNED, subject to a demonstrated use case.** Model serving and model/data-drift observability may justify FastAPI/BentoML, Evidently, or Grafana. Those services are not implemented today.

First define who consumes predictions, latency/batch needs, version selection, provenance, retention, drift definitions, and operator actions. Preserve explicit promotion, offline inference, and optional infrastructure. Completion requires validated service contracts, failure behavior, privacy boundaries, and monitoring against a reproducible reference dataset.

### Desktop graph and stress exploration

**PLANNED.** Build on cached graph artifacts for ETF search/comparison, overlap/similarity views, graph exploration, and a stress lab. Surface data dates, coverage, model provenance, signed exposure semantics, and scenario assumptions. Do not turn direct shock outputs into buy/sell signals or imply learned propagation.

Completion requires validated analytical results, usable empty/stale states, cancellation/background responsiveness, and packaging tests. Visualization must not hide missing data or force training/network work at startup.

### Orchestration deployment

**PLANNED.** Convert definition-level foundations into target-environment evidence: scheduler/DAG execution, built training images, dataset/container access, shared artifact storage, SDK/container/cluster runs, and candidate review.

Preserve Airflow data ownership, Kubeflow ML ownership, separate metadata databases, provider backoff, and explicit promotion. Successful compilation alone does not complete this workstream. Deployment infrastructure remains optional for the desktop.

### Windows release preparation

**PLANNED.** Verify builds on fresh machines, dependency/license packaging, signing, installation/uninstallation, and an update mechanism. Measure startup time and package size for the produced artifact. A closed-app scheduled refresh is deferred until an explicit user opt-in and silent sync contract exist.

Completion requires reproducible release artifacts, successful install/run/uninstall tests, local data preservation, credential handling, and verification under the target Windows security policy.

## Long-term research

**EXPLORATORY.** Expand only when coverage, request budgets, and analytical value justify the cost:

- A larger official-identity ETF universe and SEC bulk N-PORT ingestion with incremental provenance-aware storage.
- Richer graph metrics, advanced propagation research, and larger temporal datasets with out-of-time controls.
- Cross-provider price validation without silently mixing adjustments or licenses.
- Broader native/Python integration after measured API value is established.
- Point-in-time macro inputs, calibration, and uncertainty analysis when usable revision-aware data exist.
- R statistical work or Scala/high-volume processing when a specific workload exceeds the current approach.
- Broader production infrastructure only after research/deployment requirements are demonstrated.

Mandatory paid infrastructure, automatic promotion, and production trading connectivity are not implied by these directions.

## Explicit non-goals

Real order routing, broker/exchange connectivity, investment recommendations, buy/sell signals, profitability claims, causal contagion claims, mandatory paid data, and automatic model promotion are outside current scope. A localhost benchmark is not exchange latency, and a holdings scenario is not a causal forecast.

## Technical debt and known constraints

- Sparse/missing public identifiers, classifications, and history constrain coverage; preserve uncertainty instead of fabricating data.
- Graph edge aggregation can collapse an all-null weight group to `0.0`; review null-preserving aggregation before treating graph missing-weight counts as complete source coverage evidence.
- The file-based Python/C++ boundary carries limited metadata; retain the authoritative graph/data manifest externally.
- Session recovery, graph mapping negotiation, and completed-session validation are absent from the synthetic feed.
- Histogram quantiles, callback-only TCP allocation counts, repeated-frame decoder workloads, and WSL scheduling limit benchmark interpretation.
- Windows Application Control can block specific native libraries; do not weaken security to satisfy research imports.
- SQLite ownership and cross-environment file access require one deliberate writer path per database.
- Orchestration deployment, release signing, and optional live/GPU integrations need their own evidence.

Current factual constraints remain in [project status](PROJECT_STATUS.md); benchmark details remain in [native performance](NATIVE_PERFORMANCE.md).

## Completion criteria

For every workstream, define input/output contracts, factual prerequisites, reproducible fixtures, acceptance evidence, and remaining limitations. Preserve existing lint/typing/offline tests and relevant native parity/sanitizer checks. Update the status and architecture documents when behavior changes; attach benchmark evidence to performance claims. Keep source, credentials, local histories, model artifacts, and public documentation boundaries clear.
