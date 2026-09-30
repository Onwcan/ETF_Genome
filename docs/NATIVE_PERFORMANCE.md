# Native performance measurements

Measured locally on 30 September 2026. These results describe the synthetic
localhost workload and this machine. They do not establish exchange latency,
cross-machine performance, trading profitability, or a concurrency speedup.
Remote CI validates correctness; it did not produce these benchmark results.

## Machine and toolchain

| Item | Observed value |
| --- | --- |
| Machine | x86_64, local WSL2 environment; no hostname recorded |
| CPU | Intel Core Ultra 9 285HX, 24 logical CPUs exposed to Linux |
| OS | Ubuntu 26.04 under WSL2 |
| Kernel | 6.18.33.2-microsoft-standard-WSL2 |
| Compiler | GCC 15.2.0, Ubuntu 15.2.0-16ubuntu1 |
| CMake | 4.2.3 |
| Standard/build | C++20 / Release |
| Compile flags | `-O3 -DNDEBUG -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -std=c++20` |
| Affinity | Disabled; allowed logical CPU ids 0 through 23 |
| Allocation instrumentation | Disabled for the five performance runs; separate enabled verification run |
| perf | NOT RUN for the recorded measurements |

The runs were performed sequentially after local builds/tests finished. Other
desktop and OS activity, power policy, CPU frequency, thermal state, virtualization,
and core migration were not controlled or recorded. The host is a development
machine, not an isolated production server. Metadata reflects runtime discovery
and active build flags; it omits personal paths and hostnames.

## Workload and timing boundaries

Five fresh processes each ran `--mode all --events 10000000`. Each component
warmed up with 10000 events. The queue capacity was 1024 messages. Price frames
were 48 bytes. Exposure/TCP used a synthetic graph with 1024 securities, 128
funds, and 8192 links, including signed and missing weights. Graph construction,
CSV/file I/O, loading, and warmup were outside measured durations.

| Component | Latency sample | Throughput duration |
| --- | --- | --- |
| SPSC | Producer timestamp before push through consumer pop, including full-queue wait | Worker start-barrier release through final consumer completion; excludes thread construction and joins |
| Decoder | One `feed` call on a reused preencoded frame, including callback/checksum and decoder timestamp | Entire decode loop, including clocks, validation, checksum, and histogram collection |
| Exposure | One indexed price update, including initial reference-price assignments | Event generation, update, clock calls, and histogram collection; no full-fund output pass |
| TCP | Synthetic same-host send timestamp through exposure callback completion | Client connect/setup, network/consumer startup, receive/decode/queue/update, and worker joins; server listen and warmup are outside |

The decoder microbenchmark uses one valid preencoded PriceUpdate repeatedly. It
measures steady-state decoding, not serialization, diverse branches, malformed
input, or fragmented TCP reception. Separate correctness tests cover those
decoder cases. The SPSC microbenchmark yields on full/empty; the TCP pipeline
uses notification waits. They are different workloads and cannot be subtracted
to derive an isolated network cost.

Short decoder/exposure latency includes clock and function-call overhead. The
histogram update is outside each component's operation-latency interval but
inside total throughput duration. Loopback end-to-end includes sender write
backpressure, kernel buffering, scheduling, decoding, queueing, and callback.
All TCP histograms include the three control frames as well as price updates.
Measurements share one host monotonic clock; they are not UTC/exchange timestamps.

## Five-run results

Throughput below is the median across five runs, with the minimum/maximum run
rates shown separately. Each latency row comes from the actual run whose
throughput is the median: SPSC run 5, decoder run 5, exposure run 3, TCP run 4.
These are per-run quantiles, not pooled samples or medians of independent
quantiles. `M/s` means million messages/second; all latency values are ns.

| Component | Events per run | Median M/s | Rate range M/s | p50 | p90 | p95 | p99 | p99.9 | Exact max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SPSC | 10000000 | 28.490 | 27.914–30.901 | 36863 | 38911 | 43007 | 77823 | 114687 | 1207814 |
| Decoder | 10000000 | 15.179 | 14.979–15.356 | 49 | 51 | 52 | 88 | 119 | 1186743 |
| Exposure update | 10000000 | 17.929 | 17.593–18.058 | 37 | 41 | 41 | 44 | 94 | 1132883 |
| TCP end-to-end | 10000003 | 4.002 | 3.983–4.010 | 90111 | 311295 | 360447 | 557055 | 753663 | 1563698 |

The TCP count comprises 10000000 price updates plus SnapshotStart, Heartbeat,
and SnapshotEnd. Each run transferred 480000100 bytes. The representative TCP
run processed 192.077 million bytes/second. The representative decoder rate
corresponded to 728.601 million encoded bytes/second. Bytes/second is not a
meaningful standalone metric for the in-memory queue/exposure modes.

Representative TCP stage histograms (run 4), each with 10000003 samples:

| Stage | p50 ns | p90 ns | p95 ns | p99 ns | p99.9 ns | Exact max ns |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Send to decode | 69631 | 278527 | 294911 | 376831 | 655359 | 1552889 |
| Decode to callback start | 13823 | 47103 | 155647 | 262143 | 311295 | 1429807 |
| Callback processing | 40 | 52 | 83 | 101 | 143 | 122257 |

Quantiles use fixed histogram bin upper bounds, nearest-rank, capped at the
observed maximum. Bins are exact below 1024 ns, then have under 6.25% bin
overestimation plus integer rounding. Min/max are exact. Stage quantiles do not
add to an end-to-end quantile: they may describe different individual events.
Large maxima demonstrate scheduling tails despite small typical operation times.

Every performance run had zero decode errors, sequence gaps, duplicates,
out-of-order observations, and invalid timestamps. Component checksums matched
across fresh processes. Failed push attempts were 436191–725528 for SPSC and
37575–97217 for TCP; retries preserve the same message. These are backpressure
attempts, not dropped events. The representative checksums were 5114877120 for
SPSC, 999000000000 for decoder, 0.12795764536200713 for exposure, and
-0.0022956417139528757 for TCP. Exposure and TCP use different generated price
streams, so their checksums are not expected to match one another.

## Allocation verification

A separate Release invocation ran all modes with 100000 price updates and
`--allocations` after 10000-event warmup. A deterministic self-check made 11
explicit volatile function-pointer calls and observed all 11. It covers scalar,
array, aligned, nothrow, nested scopes, and independent thread-local tracking,
avoiding compiler-permitted new-expression elision in the self-check.

| Measurement | Observed successful C++ operator-new calls | Measured scope |
| --- | ---: | --- |
| SPSC | 0 | Producer and consumer event loops; excludes thread startup/reporting |
| Decoder | 0 | Feed, callback, and latency collection loop |
| Exposure | 0 | Generated event, indexed update, and latency collection; excludes graph setup |
| TCP | 0 | Consumer exposure callback only; excludes network, decoder, queue, and thread setup |

The executable's benchmark-only replacement hooks count successful C++
operator-new calls in enabled thread-local scopes. They do not count direct
malloc/calloc/realloc, mmap, external allocator internals, untracked threads, or
optimized-away allocations. A zero field with `allocation_measurement=false`
is unmeasured and must not be interpreted as evidence. This verifies the named
preallocated loops, not zero allocations across the whole application or TCP
path. Instrumented timing is kept separate from the performance table.

## Correctness context

The verification strategy and dated evidence for GCC, Clang, MSVC, sanitizers,
Python regression checks, and numerical parity are maintained in
[VALIDATION.md](VALIDATION.md). That correctness evidence is separate from the
local GCC benchmark environment above. GitHub runner timing is not used in this
performance table, and sanitizer timing is not a performance measurement.

## Reproduction

Run from the repository root with an available Linux C++20 toolchain:

```sh
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Release \
  -DETF_GENOME_WARNINGS_AS_ERRORS=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build/native --parallel 4
ctest --test-dir build/native --output-on-failure
mkdir -p reports/native-performance
for run in 1 2 3 4 5; do
  ./build/native/etf-genome-benchmark --mode all --events 10000000 \
    > "reports/native-performance/release-run-${run}.jsonl"
done
./build/native/etf-genome-benchmark --mode all --events 100000 --allocations \
  > reports/native-performance/allocation-check.jsonl
```

Raw local JSON Lines and the computed summary are retained as ignored local
reports; they are not distributed as research data. The commands above choose
`reports/native-performance/` for new runs. Public aggregate results above are
the recorded local evidence. Use the same build, event counts,
graph, affinity policy, and measurement scopes for comparisons, retain every
run, and report variability. Separate sanitizer commands are in
[native/README.md](../native/README.md). Python imports must point to this source
checkout when using an interpreter installed against another editable checkout.

## Interpretation and limits

Known limits include unavailable local perf evidence,
uncontrolled WSL scheduling/power conditions, reused-frame decoder workload,
approximate histogram quantiles, callback-only TCP allocation measurement,
external graph-id/tick mapping, no session recovery/completion validation, and
possible accumulated double rounding over long price streams. The engine is a
synthetic systems foundation; full pybind11 and temporal forecasting remain
unimplemented. Future profiling and integration work is described in the
[project roadmap](ROADMAP.md).
