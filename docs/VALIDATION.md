# Local publication validation

## Phase 8 native foundation

The C++20 market-data extension was verified locally on 30 September 2026:
Release, ASan/UBSan, and TSan each passed 9/9 native tests; portable-only Release
passed 8/8. Python checks passed with 178 tests, two opt-in live skips, and one
Git-exercising publication test deliberately deselected. New parity checks cover
binary/CSV equality, corruption rejection, and source-alias overwrite prevention.
The privacy check used source-file enumeration without Git access. Read
[NATIVE_PERFORMANCE.md](NATIVE_PERFORMANCE.md) for measurements, environment,
sanitizer scope, and unavailable Windows/Clang/perf verification.

## Earlier publication preparation

Verified on 30 September 2026 against this source checkout. These results are
local evidence; the GitHub workflows must run after publication before their
status can be claimed.

| Check | Result |
| --- | --- |
| Ruff lint and formatting | Passed |
| mypy | Passed, 111 application modules |
| Python suite including native parity | 177 passed; 2 opt-in live integrations skipped |
| Offline synthetic analytics | Passed, 24 stored holding rows across two snapshots |
| Desktop source smoke, empty cache | Passed; unavailable holdings/models shown explicitly |
| Python wheel build | Passed with existing build dependencies; no dependency resolution performed |
| Native GCC release | All 4 CTest cases passed |
| Native AddressSanitizer + UndefinedBehaviorSanitizer | All 4 CTest cases passed |
| Native ThreadSanitizer | All 4 CTest cases passed without race diagnostics |
| Python/C++ calculation parity | Passed for signed/missing weights, ambiguous aliases, and quoted CSV |
| Publication candidate scan | No detected credential/contact/path findings; generated/private outputs excluded |

Python verification used Python 3.12 and existing installed dependencies, with
imports explicitly directed to this checkout's `src` directory. Native
verification used GCC 15.2 under Linux/WSL2. A native MSVC build, a fresh Windows
executable build, optional training runs, external provider access, and deployed
orchestration were not verified in this publication pass. CI supplies Linux
GCC/Clang, Windows MSVC, Python checks, and calculation parity jobs.

The native tests include a scalar exposure reference, finite-value validation,
CSV parsing and bounds, queue capacity and wraparound, concurrent FIFO transfer,
and agreement between sequential and SPSC replay. Timing from the synthetic
replay is workload-specific; it is not an exchange latency measurement.

Run the commands in [README](../README.md), [CONTRIBUTING](../CONTRIBUTING.md), and
[native documentation](../native/README.md) to repeat the checks. The publication
guard reports locations and reasons without printing matching credential values.
Use `python scripts/check_publication.py --staged` to inspect actual indexed
contents, including files added with force. Pattern checks cannot establish that
every possible secret or personal detail is absent; review remains necessary.
