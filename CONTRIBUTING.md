# Contributing

ETF Genome combines Python data and research workflows with a C++20 native systems layer. Start with the [README](README.md), [documentation index](docs/README.md), and [project status](docs/PROJECT_STATUS.md). Future work belongs in the [roadmap](docs/ROADMAP.md).

## Development

Use Python 3.12 in a virtual environment and work from the repository root. Install the same extras as the Python CI job so the full test suite and type checks can import the research modules:

```bash
python -m pip install -e ".[desktop,dev,ml,research,training]"
```

The synthetic vertical slice and ordinary tests do not require provider credentials or external datasets. Experiment tests use temporary local tracking stores and offline Weights & Biases runs.

Before submitting a Python change, unset `ETF_GENOME_OFFLINE_MODE` or set it to `false` so tests can exercise their fake online paths. Keep the live-test opt-in switches unset, then run:

```bash
python -m ruff check src tests apps scripts
python -m ruff format --check src tests apps scripts
python -m mypy
python -m pytest
python scripts/check_publication.py
```

For native changes, configure and build `native/` with CMake 3.16+ and a C++20 compiler, then run:

```text
ctest --test-dir build/native -C Release --output-on-failure
```

Use synthetic fixtures for offline tests. Add regression coverage for changes that affect calculations, parsing, concurrency, model compatibility, or point-in-time availability. Explain any checks you could not run; do not substitute anticipated results for evidence.

To run the optional cross-language parity test, set `ETF_GENOME_NATIVE_BINARY` to the built executable and run `python -m pytest tests/integration/test_native_parity.py`. Without that setting the test skips. The native workflow configures this automatically. Follow the [native developer guide](native/README.md) for build options, platform support, and sanitizers.

The [validation guide](docs/VALIDATION.md) records verification strategy and evidence. Correctness checks and controlled performance measurements serve different purposes; describe benchmark conditions when reporting throughput or latency.

## Design expectations

- Keep source acquisition behind provider interfaces and preserve provenance and adjustment semantics.
- Preserve signed weights and missing values. A missing weight is not zero exposure knowledge.
- Use publication dates for historical holdings availability and chronological evaluation for time-dependent targets.
- Keep research dependencies out of desktop imports and make model promotion explicit.
- Keep the native CSV interface aligned with Python shock semantics, including ambiguous ticker handling.
- Document a queue's producer/consumer assumptions and observable overflow behavior when modifying event processing.

Small, focused pull requests are easiest to review. Explain the problem, the resulting behavior, and relevant validation. Do not describe research scores as trading profitability, production latency, or guaranteed forecasts.

## Data and privacy

Never include API keys, SEC contact addresses, `.env` files, local user paths, downloaded histories, trained artifacts, private logs, or application caches in a pull request. Public provider access does not automatically grant redistribution rights. Share a minimal synthetic reproduction instead of a local dataset. Follow [SECURITY.md](SECURITY.md) for sensitive reports.
