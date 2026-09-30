# Phase 8 roadmap: temporal shock research

> Historical proposal, retained in full. The active Phase 8 is now the native C++20 market-data foundation documented in [NATIVE_ARCHITECTURE.md](NATIVE_ARCHITECTURE.md). Temporal research has moved to [Phase 11](PHASE11_ROADMAP.md), after Phase 9 performance engineering and Phase 10 Python/C++ integration. References to Phase 8 below describe the original proposal.

**Status: design only.** This document summarizes the original proposed research phase. It does not describe implemented temporal services, temporal training setup, trained models, or available temporal CLI commands. Earlier local development prompts and machine-specific information are deliberately omitted from the public design.

The objective is to compare a temporal graph model with direct holdings exposure and simpler temporal baselines. Its output would be a research estimate of next-session ETF response, with coverage and evaluation limits stated explicitly. It would not establish causal shock propagation, profitable trading, or automated execution.

## Architecture

| Boundary | Responsibility |
| --- | --- |
| Windows application | PySide6, cached analytics, existing local risk inference |
| Linux / WSL2 research | Isolated Python 3.12, PyTorch, temporal training, optional GPU acceleration |
| Artifact exchange | Explicit export of validated datasets and model artifacts with fingerprints |

Research virtual environments and an optional training cache would live on the Linux filesystem. Canonical source datasets remain authoritative; copied research data carry source fingerprints and copy metadata. Windows paths must be discovered rather than hard-coded. The desktop would not load arbitrary WSL paths or acquire a PyTorch dependency.

Environment validation would begin with a CPU tensor operation and a tiny training smoke test. CUDA is optional and cannot be required for correctness. PyTorch Geometric would be evaluated after PyTorch works; an explicit PyTorch message-passing implementation with GRU is a fallback. No Windows security changes are part of this design.

## Data scope

Preserve the existing configured graph universe before increasing breadth. Resolve funds through official identities and report unresolved or ambiguous entries. Do not invent SEC series identifiers or security tickers.

Select approximately 150–200 price-eligible securities with a configurable cap. Ranking would use documented deterministic graph criteria such as degree, aggregate absolute weight, maximum weight, and reference-fund coverage. Report signed and absolute exposure coverage where relevant, including minimum and median ETF coverage. Missing histories and excluded securities remain explicit.

Use the existing market provider boundary for daily ETF and selected-security prices. Calculate a request budget before downloading, respect current provider limits, support incremental resumable sync, and retain provider and adjustment provenance. Optional secondary sources stay separate rather than silently replacing series. This design does not require a paid data subscription or hosted training service.

## Temporal dataset

Graph states become valid when their filings are publicly available. Each state has a validity interval, source accessions, and a fingerprint. Portfolio report dates cannot make unpublished holdings available to an earlier sample.

Features would include trailing security returns, volatility, shock measures, ETF features, and observed coverage. Sequences must align input time with the next-session target, respect graph-state transitions, and explicitly handle warm-up and missing dates. Low-coverage samples are excluded using a documented rule.

Chronological train, validation, and final-test ranges are fixed before training. Target windows must not cross split boundaries. Scaling, thresholds, feature selection, early stopping, and tuning use only the appropriate training/validation data. The final test does not control model architecture or training length.

Dataset fingerprints would include universe membership, graph states, price provenance, feature and target versions, sequence configuration, and split configuration.

## Baselines and evaluation

Compare a zero-response baseline, the direct mechanical exposure calculation where mathematically comparable, a non-graph neural baseline, a temporal baseline, and a modest graph encoder with GRU. Establish one stable model before a small optional tuning study.

Report MAE, RMSE, R², and descriptive correlation separately for validation and final test. Include pooled and selected per-ETF metrics, showing QQQ separately. Define large-shock subsets before final evaluation and report their sample sizes. Directional accuracy, if shown, is a secondary diagnostic rather than trading accuracy.

A QQQ case study would use a deterministic test-period selection rule and show the public graph state, major security moves, covered exposure, direct approximation, observed response, and model estimate. Choose the case by the rule, not by favorable model performance.

## Artifact and tracking contract

Research outputs would carry the model state, feature schema, graph schema, price-universe manifest, and metadata: target, sequence length, date ranges, seeds, software/device versions, fingerprints, and metrics. Export back to the Windows project through a controlled command and verify compatibility.

Experiment tracking defaults to disabled or offline. Raw filings and market histories are not uploaded. A temporal model remains an experiment or candidate; it is not automatically promoted into desktop production.

## Acceptance criteria

1. Existing Python lint, typing, and offline regression checks continue to pass without PyTorch, WSL, or CUDA.
2. Linux Python 3.12 and PyTorch CPU operations are verified; CUDA and optional PyG status are recorded factually.
3. Security selection, request budgeting, cache resume, provenance, and coverage are reproducible.
4. Graph-state tests prove publication-date transitions and absence of future holdings.
5. Temporal tests cover feature lookback, next-session alignment, split isolation, missing dates, and changing graph states.
6. Tiny synthetic tests cover message passing, output shape, learning on trivial data, and model serialization.
7. Baselines and temporal graph training produce separate validation and untouched final-test reports.
8. Subset metrics and a deterministic case study are reported only when the available data support them.
9. Exported artifacts have verified fingerprints and remain outside the desktop dependency graph.

Serving infrastructure, monitoring, a graph GUI, automatic model promotion, automated trading, and thousands-of-fund expansion are outside Phase 8. A later phase may consider them after the research evaluation is reproducible.
