# Contributing

ETF Genome is a research application with explicit boundaries between local analytics, data acquisition, training, and desktop inference. Start with the [README](README.md) and [project status](docs/PROJECT_STATUS.md) to distinguish working code from roadmap ideas.

## Development

Use Python 3.12 in a virtual environment and install `.[desktop,dev,ml]`. Work from the repository root. The synthetic vertical slice and ordinary tests do not require credentials or external data.

Before submitting a Python change, unset `ETF_GENOME_OFFLINE_MODE` or set it to `false` so tests can exercise their fake online paths. Keep the live-test opt-in switches unset, then run:

```bash
python -m ruff check src tests apps scripts
python -m ruff format --check src tests apps scripts
python -m mypy
python -m pytest
python scripts/check_publication.py
```

For native changes, configure and build `native/` with CMake 3.16+ and a C++17 compiler, then run:

```text
ctest --test-dir build/native -C Release --output-on-failure
```

Use synthetic fixtures for offline tests. Add regression coverage for changes that affect calculations, parsing, concurrency, model compatibility, or point-in-time availability. Explain any checks you could not run; do not substitute anticipated results for evidence.

To run the optional cross-language parity test, set `ETF_GENOME_NATIVE_BINARY` to the native executable's absolute path and run `python -m pytest tests/integration/test_native_parity.py`. Without that setting the test skips. The Python and native GitHub Actions workflows in `.github/workflows/` provide repeatable CI checks; review the actual run results before reporting them as passing.

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
