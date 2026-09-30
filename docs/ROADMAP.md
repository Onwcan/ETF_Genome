# Roadmap

See [Project status](PROJECT_STATUS.md) for implemented features and validation
limits. Phase 8 supplies the [native systems foundation](NATIVE_ARCHITECTURE.md).
Phase 9 performance engineering and Phase 10 pybind11 integration remain future work.
[Phase 11](PHASE11_ROADMAP.md) retains the temporal research design.
Earlier phase numbers describe development history rather than
deployment maturity.

## Next milestones

- Expand the desktop workflow with ETF search, comparison, similarity views, and
  clearer model/data provenance, using cached data before network refreshes.
- Improve historical holdings coverage and point-in-time market/macro datasets
  while preserving publication dates, provider provenance, and rate limits.
- Evaluate risk models with chronological holdouts, calibration, and uncertainty
  measures before presenting stronger forecasting claims.
- Validate graph learning and temporal experiments in a working research
  environment. Direct holdings shocks remain separately labeled scenarios.
- Turn orchestration prototypes into tested deployment configurations with
  built training images, shared artifact storage, and explicit candidate review.
- Benchmark the native C++ exposure/replay implementation on reproducible inputs
  and investigate improvements supported by profiling.
- Prepare a Windows release with signing, installation/uninstallation, updates,
  dependency/license review, and verification on a fresh machine.

## Current boundaries

The project is a research and engineering prototype. It does not connect to a
broker, execute orders, or implement a production exchange gateway. Direct shock
results do not model learned secondary propagation. Research/orchestration tools
remain separate from the desktop runtime. Downloaded data, locally trained
artifacts, credentials, and release binaries are not supplied in the source repo.

Scenarios and model estimates should always retain their input dates, assumptions,
and limitations. A stress result or risk estimate is not a trading instruction.
