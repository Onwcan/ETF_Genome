# Binary formats

ETF Genome uses two separate version-1 formats: a synthetic market-event wire
protocol and an optional static exposure snapshot. Integers are explicit fixed
width and big-endian. Runtime struct padding/alignment is never serialized.
The supported targets have eight-bit bytes; graph storage additionally requires
64-bit IEEE-754 doubles. Neither format is an exchange protocol.

## EGMD market events

Every frame begins with this 32-byte header. Payload length excludes the header.
Maximum accepted frame storage is 64 bytes; current valid frames use 32, 36, or
48 bytes. Version 1 requires an exact length for each known type.

| Offset | Bytes | Field | Rule |
| --- | ---: | --- | --- |
| 0 | 4 | Magic | ASCII `EGMD` |
| 4 | 2 | Version | unsigned, exactly 1 |
| 6 | 2 | Type | unsigned, values below |
| 8 | 4 | Payload length | unsigned, exact type-specific size |
| 12 | 4 | Reserved | zero |
| 16 | 8 | Sequence | unsigned; synthetic session begins at zero |
| 24 | 8 | Sender timestamp | unsigned monotonic nanoseconds |

| Type | Value | Payload bytes | Payload fields in order |
| --- | ---: | ---: | --- |
| Heartbeat | 1 | 0 | none |
| PriceUpdate | 2 | 16 | instrument u32, price ticks i64, quantity u32 |
| Trade | 3 | 16 | instrument u32, price ticks i64, quantity u32 |
| SnapshotStart | 4 | 4 | instrument count u32 |
| SnapshotEnd | 5 | 0 | none |

For PriceUpdate/Trade, instrument is at frame offset 32, price at 36, and quantity
at 44. Signed price uses its 64-bit two's-complement bit representation.
Instrument ids are zero-based indices in sorted canonical graph security ids.
Price/quantity units are externally agreed. The price exposure consumer rejects
nonpositive prices, but the byte decoder accepts all representable signed values.
Trade and quantity are preserved for protocol demonstrations; they do not alter
the current exposure engine. SnapshotStart count must match the engine universe.

The count does not carry identities or a graph fingerprint. Equal counts cannot
detect a mismatched mapping. The producer/consumer must agree on the same graph
and tick unit before starting. This phase has no symbology negotiation.

The synthetic server emits SnapshotStart, Heartbeat, N PriceUpdates, SnapshotEnd
with consecutive sequences, then EOF. Sequences do not wrap. Gap counts mean
missing sequence values, not gap events. A repeat of the high-water value counts
as duplicate; an older value counts as out-of-order, including older duplicates.
Tracking uses bounded state, not an unbounded history, and does not retransmit or
discard anomalous valid frames.

## Framing and decoder contract

TCP is a byte stream: one send/read does not define one frame. The incremental
decoder accumulates a header, validates it, accumulates its declared payload,
then calls a nonthrowing sink. Arbitrary fragmentation and coalescing are
supported. The buffer is fixed at 64 bytes. Bad magic, unsupported version,
unknown type, wrong/oversized length, or nonzero reserved fields stop decoding
with a sticky error; reset is explicit, with no scanning for a new magic marker.

`feed()` returns bytes consumed, accepted frame count, and error. If a sink
returns false, the completed message is retained and `SinkStopped` is returned.
No later bytes are consumed. Retry delivery with empty input, then supply the
unconsumed tail. The caller owns that tail. A null sink is `InvalidSink`.
`finish()` reports truncation for a partial or undelivered frame. An empty
decoder at EOF is clean; framing validation does not enforce the full session
order or require SnapshotEnd. The network feed blocks its sink stop-aware on a
full queue, preserving accepted valid messages.

## Clock and latency meaning

Sender and client must run on the same host/clock domain to subtract timestamps.
Linux chooses `CLOCK_MONOTONIC_RAW` on its initial successful probe; otherwise
it uses `steady_clock`. The clock domain does not switch during processing.
These timestamps are neither UTC nor exchange timestamps. Cross-machine or
cross-VM subtraction is unsupported. The decoded timestamp is recorded locally
after a complete frame is decoded and is never sent on the wire.

The consumer records callback start/finish. Latencies are send-to-decode,
decode-to-start, start-to-finish, and send-to-finish, in nanoseconds. Zero or
unordered send/decode/start/finish stamps increment `invalid_timestamps` and
are omitted from all four histograms. This avoids turning invalid measurements
into artificial zero-latency samples. The sender timestamp precedes sending,
so TCP transport samples include partial-write and kernel backpressure delays.

The fixed histogram stores exact bins for 0 through 1023 ns, then 16 sub-bins per
power of two through u64 max. Quantiles use nearest-rank bin upper bounds capped
at observed maximum. Above 1023 ns, bin overestimation is under 6.25% plus integer
rounding; min/max are exact. Saturation is explicit. Empty histograms return zero
and must be interpreted with sample count.

## EGEXPOS1 graph snapshot

This cold-load file format has a 64-byte header followed by an exactly sized
payload. It is independent of EGMD and preserves a static exposure reverse index.

| Offset | Bytes | Field |
| --- | ---: | --- |
| 0 | 8 | ASCII `EGEXPOS1` |
| 8 | 2 | Version = 1 |
| 10 | 2 | Flags = 0 |
| 12 | 4 | Header size = 64 |
| 16 | 4 | Fund count F |
| 20 | 4 | Security count S |
| 24 | 8 | Link count E |
| 32 | 4 | Alias count A |
| 36 | 4 | Reserved = 0 |
| 40 | 8 | Payload size |
| 48 | 8 | FNV-1a 64-bit payload checksum |
| 56 | 8 | Reserved = 0 |

Payload order is:

1. F fund ids, then S security ids, each as u32 byte length followed by bytes.
2. A aliases: length-prefixed ticker followed by u32 security index.
3. S+1 u64 offsets into the contiguous links.
4. E links: u32 fund index, u8 weight-present flag, three zero reserved bytes,
   and u64 bits of an IEEE-754 double weight. Each link occupies 16 bytes.

F/S are bounded at 100000 each; E/A at 1000000 each; payload at 64 MiB. Each id
contains 1 through 4096 non-NUL bytes. Source exporters use UTF-8, while the
native reader treats ids as opaque bytes and does not validate Unicode. Fund
and security ids must be sorted and unique. Offsets start at zero, are
nondecreasing, stay within E, and end at E. Fund/alias indices must be in range.
Flags are zero/one, weights are finite, and a missing weight stores zero.
Duplicate holdings remain separate additive links; alias ambiguity is preserved.

The loader checks bounded header counts and minimum possible payload size
before allocation, checks exact file length and payload checksum, then validates
ids, offsets, links, and aliases before publishing a graph. Truncation, trailing
bytes, impossible counts, invalid offsets, flags, weights, or reserved fields
are rejected. Weight sums are reconstructed in canonical sparse order with
scaled compensated summation to avoid overflowing intermediates that cancel.

FNV-1a uses offset basis 14695981039346656037 and prime 1099511628211, over payload
bytes only, with u64 wraparound. It detects accidental corruption and provides
no cryptographic authenticity. Snapshot versioning is explicit; unknown
versions are rejected. The file does not carry as-of dates, provider provenance,
currency/tick units, or publication metadata. Python must select and retain a
valid point-in-time source before export.
