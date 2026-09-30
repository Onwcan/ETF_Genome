# Native C++20 market-data and exposure foundation

This C++20 module extends ETF Genome's Python research with a portable sparse
exposure core and a Linux synthetic market-data pipeline: binary serialization,
incremental decoding, nonblocking TCP/epoll, a bounded SPSC queue, persistent
price exposure state, and separate component benchmarks. Checked-in examples and
feed events are synthetic. The core uses the C++ standard library and platform
threads; Linux networking uses POSIX APIs.

The module demonstrates immutable graph ownership, preallocated evaluation
workspaces, explicit atomics, FIFO event transfer, input validation, and numerical
cross-checks. It has no exchange connection, order routing, learned propagation,
or live trading functionality. Python retains acquisition, research, ML, graphs,
and the desktop. Full pybind11 integration remains future work. See
[architecture](../docs/NATIVE_ARCHITECTURE.md), [binary protocol](../docs/BINARY_PROTOCOL.md),
and [performance and validation](../docs/NATIVE_PERFORMANCE.md).

## Build and verify

Run from the repository root with a C++20 compiler and CMake 3.16 or newer:

```sh
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Release \
  -DETF_GENOME_WARNINGS_AS_ERRORS=ON
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure

./build/native/etf-genome-native demo
./build/native/etf-genome-native shock \
  --edges native/examples/synthetic_edges.csv \
  --shocks native/examples/synthetic_shocks.csv
./build/native/etf-genome-native replay 200000
```

On Windows with a multi-configuration generator, the binary is normally
`build/native/Release/etf-genome-native.exe`. A single-configuration generator
normally places it in `build/native/etf-genome-native.exe`. WSL can build and run
the Linux executable with the commands above. Build artifacts belong in ignored
`build/` directories.

Separate sanitizer builds are available for GCC and Clang on supported platforms:

```sh
cmake -S native -B build/native-asan -DCMAKE_BUILD_TYPE=Debug \
  -DETF_GENOME_ENABLE_SANITIZERS=ON
cmake --build build/native-asan
ctest --test-dir build/native-asan --output-on-failure

cmake -S native -B build/native-tsan -DCMAKE_BUILD_TYPE=Debug \
  -DETF_GENOME_ENABLE_TSAN=ON
cmake --build build/native-tsan
ctest --test-dir build/native-tsan --output-on-failure
```

ASan/UBSan and TSan use separate builds. These options are unsupported under MSVC;
use the ordinary MSVC build or a supported GCC/Clang environment. Current local
verification uses GCC 15.2 in Ubuntu 26.04 under WSL2. Windows/MSVC and Linux Clang
were unavailable locally. CI configuration does not establish a remote result.
Current test evidence is recorded in the performance document.

`ETF_GENOME_BUILD_NETWORK` defaults to `ON` on Linux and `OFF` elsewhere. Set it
to `OFF` to build only the portable core. Enabling it on Windows produces a clear
configuration error. Shock/replay, decoder, snapshots, exposure, SPSC, and their
component benchmarks are portable; the feed executables and TCP benchmark
require Linux. No network executable is required by the desktop.

## CSV interface

`shock --edges PATH --shocks PATH` reads these exact headers, in this order:

```csv
etf_node_id,security_node_id,security_ticker,portfolio_weight
synthetic:ETF_A,synthetic:SEC_1,SYN1,0.2
synthetic:ETF_A,synthetic:SEC_2,SYN2,-0.1
synthetic:ETF_A,synthetic:SEC_4,SYN4,
```

```csv
key,shock
syn1,-0.1
synthetic:SEC_2,-0.5
SYN4,0
```

Weights and shocks are decimal fractions: `0.2` is a 20% portfolio weight and
`-0.1` is a -10% shock. An empty weight is missing. Empty tickers are accepted;
ETF/security ids and shock keys must be nonempty. No report date or availability
date is carried in this minimal interface: the Python pipeline must select a
valid point-in-time snapshot before export.

Canonical security ids take precedence over ticker lookup. Ticker lookup is
ASCII case-insensitive and succeeds only when the ticker identifies one security
in the graph. Ambiguous tickers and unknown keys are excluded with a warning on
stderr. Multiple different keys resolving to one security use the last value in
CSV order, matching Python's alias overwrite behavior. Repeated identical shock
keys are rejected; duplicate holdings remain separate additive rows.

The calculator emits CSV on stdout, with ETF ids sorted lexicographically:

```csv
etf_node_id,direct_shock,covered_weight,weight_sum,missing_weight_count
```

Errors go to stderr with exit status `2`. Successful commands use status `0`.
Quote escaping, commas inside quoted fields, quoted multiline fields, LF, CRLF,
and an optional UTF-8 BOM are supported. Numeric values must be finite, without
leading or trailing whitespace, a percent sign, or a leading `+`. Blank records
are rejected. Limits per input are 64 MiB, one million data rows, 4,096 bytes per
decoded field, and 16,384 bytes per logical record. The in-process library takes
typed vectors; its caller controls their size and lifetime.

The project exporter can produce this interface without collecting new data:

```sh
python scripts/export_native_graph.py --demo --output data/native
./build/native/etf-genome-native shock \
  --edges data/native/edges.csv --shocks data/native/shocks.csv
```

## Calculation and precision

For ETF `f` and the set of resolved shocked securities `K`:

```text
direct_shock(f) = sum(weight(f, s) * shock(s)) for s in K with reported weights
covered_weight(f) = sum(weight(f, s)) for s in K with reported weights
weight_sum(f) = sum(all reported weights for f)
missing_weight_count(f) = number of rows in K whose weight is missing
```

Short weights remain negative. Missing weights do not contribute to either the
shock or covered weight. A resolved zero shock still contributes its reported
weight to coverage and counts a missing weight. There is no renormalization,
clamping, return forecast, or secondary contagion model. `covered_weight` is
signed mass, so it is not generally a coverage percentage.

The immutable graph stores compressed offsets from securities to holdings.
After shock resolution, evaluation visits only the shocked securities' edges,
plus a pass over every ETF to reset and validate the workspace. Its work is
`O(F + K + E_K)`, where `F` is the ETF count and `E_K` is the number of holdings
rows for the shocked securities. Retained numeric graph storage is `O(F + S + E)`;
id strings and ticker lookup maps also consume memory. Construction, sorting,
alias resolution, CSV parsing, and output formatting allocate memory. Successful
evaluation and queue operations use preallocated state. Measured allocation
results are limited to the scopes documented in the performance record.

`double` is used for analytical weights and shocks. The output retains enough
decimal digits to round-trip a double. Securities are accumulated in sorted
canonical id order, and repeated holdings preserve their order within each
security. Python's source-row summation can differ in the final floating-point
bits; compare with a tolerance, not by formatting strings. This is not fixed-point
money or tick arithmetic. Nonfinite inputs and overflowing result sums are
rejected. If evaluation throws due to overflow, discard that workspace's partial
results. The engine does not carry dates, FX conversions, duration, liquidity, or
issuer valuation assumptions beyond those already represented in exported weights.

## Queue ownership and replay

`SpscQueue<T, Capacity>` reserves `Capacity + 1` slots, yielding exactly `Capacity`
usable slots without allocating after construction. Exactly one producer calls
`try_push`, and exactly one consumer calls `try_pop`. Objects must have trivial,
nonthrowing value semantics; the target must provide lock-free `size_t` atomics.
Release/acquire publication protects a complete payload and prevents the producer
from reusing a slot before the consumer has read it. Cached opposing indices and
64-byte padding reduce shared-index traffic on typical targets; padding is not a
universal statement about hardware cache-line sizes.

The queue reports full/empty immediately. The replay chooses a yield-and-retry
policy, so it preserves events and exposes backpressure through retry counters.
It uses a known event count, verifies sequence order, and joins the producer on
both normal completion and consumer exceptions. The Linux feed additionally
uses bounded notification waits and optional worker affinity. There is no
multi-producer support, persistent log, or durability guarantee. Destroy the
queue only after both participants have finished.
Concurrent graph readers need separate workspaces; a workspace belongs to one
consumer at a time.

Each legacy replay event is an independent, one-security shock scenario. It does not
maintain market prices or accumulate a changing portfolio. The default synthetic
graph has 128 ETFs, 1,024 securities, and 8,192 holdings rows, including signed
weights and missing weights. Event payloads contain sequence, indexed security,
and shock. Event generation, evaluation, and checksum accumulation use preallocated
application state inside the loop.

## Legacy replay methodology

`replay [event_count]` defaults to 200,000 events and accepts 0 through 100,000,000.
It warms each path with `min(event_count, 10000)` events, then measures a sequential
reference and a two-thread SPSC replay with `steady_clock`. Both must produce
identical event counts and checksums. Output reports elapsed seconds,
events/second, checksum, and queue retry counts.

Construction, CSV I/O, workspace allocation, and warmup are outside the reported
duration. Thread startup/join, synthetic generation, yield/retry backpressure,
workspace reset, exposure evaluation, validation, and checksum accumulation are
inside it. The sequential path performs the same event generation, evaluation,
and checksum work without the queue or second thread. This measures the complete
synthetic workload rather than an isolated queue or per-event latency.

For a comparison, use the same Release build and graph, run at least five fresh
processes, choose an event count giving sufficiently long runs, retain all raw
outputs, and report medians and spread with compiler, OS, CPU, and load conditions.
For example:

```sh
for run in 1 2 3 4 5; do
  ./build/native/etf-genome-native replay 2000000
done
```

The SPSC path may be slower for this small analytical workload; concurrency is not
a promised speedup. A throughput number does not establish tail latency or
exchange suitability. Sanitizer runs check correctness and should not be used
for performance comparisons.

Tests check signed and missing weights, alias precedence and ambiguity, duplicate
holdings, reset behavior, a scalar reference, finite/overflow validation, strict
CSV parsing and quote escaping, queue capacity/wrap, 300,000 concurrent payload
transfers, and sequential-versus-SPSC replay consistency. The repository's Python
parity tests additionally exercise the exported CSV interface when a native
binary is supplied.

## Synthetic Linux feed

Run these in separate terminals:

```sh
./build/native/etf-genome-feed-server --port 9000 --events 100000 \
  --instruments 1024 --seed 7 --rate 0
./build/native/etf-genome-feed-client --port 9000 --instruments 1024
```

Only `127.0.0.1` is accepted. The server accepts one connection, emits
SnapshotStart, Heartbeat, N PriceUpdate frames, and SnapshotEnd, then closes.
Rate zero is unpaced; a positive `--rate` requests approximate events/second
using sleeps. `--send-chunk 1` exercises fragmentation. `--timeout-ms` controls
progress deadlines, default 5000 ms. Pacing is not a precision timing guarantee.

The default client graph has 1024 securities, 128 funds, and 8192 holdings rows.
`--instruments` accepts 1 through 100000. Larger synthetic universes scale the
fund count to include every requested security. Alternatively load an explicit
graph with exactly one of `--edges CSV` or `--snapshot BINARY`:

```sh
./build/native/etf-genome-feed-client --port 9000 --edges data/native/edges.csv
./build/native/etf-genome-feed-client --port 9000 --snapshot data/native/graph.bin
```

Set the server instrument count to the graph's security count. Id `i` means
`graph.security_ids()[i]` in sorted canonical-id order. The wire carries a count,
not a mapping/fingerprint: equal counts cannot establish equal identities.
Both participants must agree on the same mapping.

SIGINT/SIGTERM handlers set a flag; main requests stop, the producer exits, and
the consumer drains accepted queued messages. Threads join before descriptors
are destroyed. A rejected callback stops processing and may leave queued events
unprocessed. An interrupted partial frame is not delivered. Clean EOF completes
framing; it does not verify an expected SnapshotEnd. There is no reconnect or
session recovery. Malformed framing is fatal to that connection.

Client output includes message/byte throughput, failed full-queue attempts,
protocol/sequence counters, invalid timestamps, exposure checksum, and transport,
queue, processing, and end-to-end quantiles. Invalid timestamps are counted and
omitted from histograms. Sequence anomalies are observed, not retransmitted or
silently deduplicated. Error output includes category and operation, and exits
nonzero.

Optional `--producer-cpu N` / `--consumer-cpu N` pin the corresponding Linux
worker; the server supports producer pinning. Default `-1` means unpinned. Denied
or invalid affinity produces an error. `--consumer-delay-us N` is a controlled
backpressure experiment and is excluded from processing latency.

## Binary exposure snapshots

CSV remains the Python export boundary. The optional native snapshot preserves
sorted ids, ticker aliases, sparse offsets, and signed/missing weights:

```sh
./build/native/etf-genome-native snapshot-save \
  --edges data/native/edges.csv --output data/native/graph.bin
./build/native/etf-genome-native snapshot-info data/native/graph.bin
./build/native/etf-genome-native shock \
  --snapshot data/native/graph.bin --shocks data/native/shocks.csv
```

Snapshot errors return status 2. The loader validates version, sizes, bounds,
offsets, weights, and checksum before exposing a graph. It allocates during
loading. Its checksum detects accidental corruption and is not authentication.
Serialization is explicit big-endian, never raw C++ object memory. Snapshot
export rejects aliases of its source CSV. The exact storage format is in
[BINARY_PROTOCOL.md](../docs/BINARY_PROTOCOL.md).

## Persistent price exposure

`PriceExposureEngine` stores one integer reference price and return per security,
and one double impact per fund. SnapshotStart validates the universe count and
resets preallocated arrays. The first positive price establishes a reference.
Later updates compute `r = price/reference - 1`, then add
`weight * (r - previous_r)` to each linked fund. Ordinary update work is
`O(degree(security))`; snapshot reset is `O(S + F)`.

Signed, duplicate, missing, and zero weights retain their graph semantics.
Trade, Heartbeat, and SnapshotEnd do not change the price-only valuation model.
Invalid instruments/prices, count mismatch, or overflow reject the callback.
Overflow may leave partial state; discard it after the fatal error. The graph
must outlive the engine; one consumer owns its mutable state. Integer ticks use
an externally agreed unit. This analytical calculation omits FX, corporate
actions, execution costs, rebalancing, and learned propagation.

## Component benchmarks

```sh
./build/native/etf-genome-benchmark --mode all --events 1000000
./build/native/etf-genome-benchmark --mode decoder --events 100000 --allocations
./build/native/etf-genome-benchmark --self-check
```

Modes are `spsc`, `decoder`, `exposure`, Linux `tcp`, or `all`. Counts are 1 through
10000000. JSON Lines output includes environment, warmup, measurement scope,
throughput, checksum, counters, and p50/p90/p95/p99/p99.9/max nanoseconds.
Setup and warmup are excluded. Histograms use nearest-rank estimates with exact
min/max. Use repeated uninstrumented Release runs for performance evidence;
Debug and sanitizer runs check correctness.

`--allocations` counts replaceable C++ operator-new calls in named scopes. TCP
instrumentation covers only the exposure callback. It cannot establish zero
allocations across sockets, threads, libc, or the whole pipeline. A dedicated
allocation self-check validates the counter. See
[NATIVE_PERFORMANCE.md](../docs/NATIVE_PERFORMANCE.md) for actual results, timing
boundaries, histogram error, and measurement limits. Benchmarks make no speedup
or exchange latency guarantee.
