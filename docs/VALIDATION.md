# Validation strategy and evidence

ETF Genome separates correctness validation from performance measurement.
Static analysis, regression tests, compiler checks, sanitizers, and numerical
parity establish evidence for the paths exercised. Native throughput and
latency require a documented local Release workload; CI runner timing is not
benchmark evidence. Full measurement boundaries and recorded results belong in
[NATIVE_PERFORMANCE.md](NATIVE_PERFORMANCE.md).

## Verified remote baseline

The baseline preceding the documentation consolidation was fully green on
30 September 2026. Both runs below completed successfully for revision
`dad56c3`:

| Workflow | Baseline result | Verified coverage | Evidence |
| --- | --- | --- | --- |
| Python and publication checks | GREEN | Python 3.12 on Ubuntu and Windows; Ruff lint/format, mypy, pytest; publication validation | [Python/publication run](https://github.com/Onwcan/ETF_Genome/actions/runs/36752368453) |
| Native C++ checks | GREEN | Linux GCC and Clang, Windows MSVC, CTest, Linux/Windows Python/C++ parity, Clang ASan/UBSan, GCC TSan | [Native C++ run](https://github.com/Onwcan/ETF_Genome/actions/runs/36752368591) |

The workflow definitions are
[checks.yml](../.github/workflows/checks.yml) and
[native.yml](../.github/workflows/native.yml). Their remote results establish
the baseline, not a pass for subsequent local documentation edits. Those edits
receive remote validation only after publication and a new workflow run.

## Local documentation validation

The documentation consolidation was checked locally on 30 September 2026 in
an isolated Python 3.12.10 environment with the CI dependency extras:

| Check | Result |
| --- | --- |
| Ruff lint | PASS |
| Ruff format check | PASS; 165 files unchanged |
| mypy | PASS; 111 source modules |
| pytest | 174 passed, 6 skipped, 1 deselected in 16.88 s |
| Filesystem publication/privacy scan | 277 intended public files; zero findings |
| Markdown links | 34 Markdown files, 193 local links; zero broken links |
| Mermaid | All 5 blocks parsed and rendered with Mermaid 11 in default and dark themes |

The native executable variable was unset, accounting for four numerical-parity
skips; the other two skips were opt-in live integrations. The Git-dependent
publication test was deselected to honor the prohibition on version-control
operations. The filesystem scan did not inspect the Git index. Diagram review
included the 14-node README architecture and used default styling, with no
repository JavaScript dependencies or diagram image assets added.

All 239 non-Markdown files in the baseline hash inventory were unchanged.
Native C++ was not rebuilt, and benchmarks were not rerun for this
documentation-only validation. The dated remote baseline above remains the
native compiler/sanitizer evidence; these local results cover the Python suite
and documentation checks.

## Python checks

Use Python 3.12 with the project's development dependencies. The Python CI
environment also installs the desktop, ML, research, and training extras so
optional modules participate in static analysis. From the repository root:

```sh
python -m pip install -e ".[desktop,dev,ml,research,training]"
python -m ruff check src tests apps scripts
python -m ruff format --check src tests apps scripts
python -m mypy
python -m pytest
```

The default suite uses synthetic fixtures and local artifacts. External SEC
and market-provider integrations are opt-in through
`ETF_GENOME_RUN_LIVE_SEC_TESTS` and `ETF_GENOME_RUN_LIVE_MARKET_TESTS`; the
remote correctness baseline leaves both disabled. Desktop tests use Qt's
offscreen mode. A passing default suite does not demonstrate fresh provider
access or a successful optional deep-learning training run.

One publication test creates and inspects a temporary Git index. When version
control operations are prohibited, deselect it explicitly:

```sh
python -m pytest -k "not test_staged_scan_reads_index_even_after_worktree_is_cleaned"
```

Record the actual passing, skipped, and deselected counts together with the
environment. Do not describe a skip as a successful integration check.

## Native compiler and sanitizer matrix

The native workflow builds C++20 with project warnings treated as errors:

| Configuration | Platform | Purpose |
| --- | --- | --- |
| GCC Release | Linux | Portable core, synthetic networking, CLI and CTest correctness |
| Clang Release | Linux | Independent compiler and warning coverage |
| MSVC Release | Windows | Portable core, CLI, decoder, queue, snapshot and exposure coverage |
| Clang Debug with ASan/UBSan | Linux | Address and undefined-behavior checks |
| GCC Debug with TSan | Linux | Race detection on exercised concurrent paths |

The POSIX sockets and epoll feed are Linux-only. A portable build can disable
networking with `ETF_GENOME_BUILD_NETWORK=OFF`. Windows does not supply a
substitute epoll implementation. ASan/UBSan and TSan require separate build
directories; the current CMake sanitizer options are not supported with MSVC.
Linux and Windows reproduction commands are maintained in the
[native developer guide](../native/README.md).

CTest covers static exposure against a scalar reference, strict CSV handling,
signed and missing weights, alias resolution, queue capacity/wraparound and
concurrent FIFO payload integrity, and scenario replay agreement. Protocol
tests cover golden big-endian bytes, all header/payload fragmentation cuts,
coalescing, malformed headers, sticky errors, EOF, sink backpressure, sequence
counters, clocks, and small known histogram datasets. Additional tests cover
persistent price exposure, binary snapshots, bounded input validation,
loopback disconnects, stop/drain behavior, invalid timestamps, and allocation
instrumentation.

Snapshot tests recompute checksums for structurally invalid counts, offsets,
aliases, flags, and weights, so checksum rejection cannot mask missing
structural checks. Regression checks also protect source-alias overwrite
prevention and finite weight sums with cancelling intermediate terms.
Recorded local CLI checks covered synthetic universes through 100000
instruments, invalid-affinity cleanup, signal-driven shutdown, and a failed
snapshot flush to Linux `/dev/full`. These checks do not prove that every
concurrency schedule or exceptional operating-system failure is safe.

## Python/C++ numerical parity

The integration suite invokes a separate native executable through
`ETF_GENOME_NATIVE_BINARY`. On Linux, after building it:

```sh
ETF_GENOME_NATIVE_BINARY=./build/native/etf-genome-native \
  python -m pytest tests/integration/test_native_parity.py
```

For a Visual Studio Release build on Windows:

```powershell
$env:ETF_GENOME_NATIVE_BINARY = ".\build\native-msvc\Release\etf-genome-native.exe"
python -m pytest tests/integration/test_native_parity.py
```

Without that variable, native parity tests are skipped. The remote native
workflow explicitly sets it on Linux and Windows. Parity cases cover signed
positions, missing weights, zero weights and multiple shocks, unknown securities,
ambiguous aliases, quoted CSV, binary/CSV scenario equivalence, and protection
against overwriting a source through a filesystem alias. Analytical double
results are compared with a numerical tolerance; native persistent-price
tests use an independent scalar reference. Full pybind11 integration is not
part of this boundary.

## Publication and privacy validation

The publication workflow checks indexed source contents with
`scripts/check_publication.py --staged`. The guard rejects generated/private
artifacts and scans for credential, contact, and personal-path patterns. It
reports locations and reasons without printing matched secret values. Its
command-line entry point invokes Git in both staged and ordinary modes.

For a pass that prohibits Git, enumerate intended public files directly from
the filesystem and use the guard's pure `scan_file(path, content)` function.
Exclude version-control metadata, credentials, datasets, model artifacts,
caches, builds, reports, and raw attachments from enumeration. Check Markdown
links and content from those same public files. This assesses filesystem
contents and does not certify the index or ignored files. Pattern scans do
not establish that every possible private detail is absent; publication still
requires reviewing the selected source contents.

## Documentation checks

Documentation changes are checked against current script names, CLI options,
CMake targets, dependency groups, implementation contracts, and recorded
evidence. Relative file links must resolve from each document; heading links
must match their targets. Mermaid blocks must parse without external assets
or custom CSS. The project has one authoritative
[roadmap](ROADMAP.md), while [project status](PROJECT_STATUS.md) describes
current implementation only.

A documentation-only pass reruns the Python checks and filesystem link/privacy
audit. It does not rebuild native C++ when native sources and build files are
unchanged. The remote baseline remains distinct from those local checks.

## Performance methodology

Use repeated fresh, uninstrumented Release processes with the same synthetic
graph, event counts, queue capacity, affinity policy, and timing scope. Retain
all raw runs, report throughput medians and spread, and associate latency
quantiles with a clearly identified run. Report compiler, flags, CPU, OS,
clock assumptions, histogram approximation, and allocation measurement scope.

The recorded local benchmark uses GCC 15.2.0 on Ubuntu 26.04 under WSL2; it is
a synthetic localhost software path. It does not measure exchange latency.
The dedicated allocation self-check proves known replacement C++ operator-new
calls are counted, but the TCP measurement covers only the exposure callback.
It does not establish allocation freedom for the whole application. Local
`perf` evidence is not available in the recorded measurements. Detailed
results and limitations are maintained in
[NATIVE_PERFORMANCE.md](NATIVE_PERFORMANCE.md).
