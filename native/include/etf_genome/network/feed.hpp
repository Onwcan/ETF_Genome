#pragma once

#include "etf_genome/market/message.hpp"
#include "etf_genome/market/protocol.hpp"
#include "etf_genome/metrics/histogram.hpp"
#include "etf_genome/network/socket.hpp"

#include <cstddef>
#include <cstdint>
#include <stop_token>

namespace etf_genome::network {

inline constexpr std::size_t feed_queue_capacity = 1024;
using MessageConsumer = bool (*)(void*, const MarketMessage&) noexcept;

enum class FeedError {
    None, System, Timeout, PeerDisconnected, Protocol, ConsumerRejected, Affinity
};
[[nodiscard]] const char* feed_error_name(FeedError error) noexcept;

struct FeedServerConfig {
    std::uint16_t port = 9000;
    std::uint64_t events = 100000;
    std::uint64_t rate_per_second = 0; // zero sends as fast as backpressure allows
    std::uint32_t instruments = 1024;
    std::uint32_t seed = 7;
    int idle_timeout_ms = 5000;
    std::size_t send_chunk_bytes = 64; // reduce for deliberate fragmentation tests
    int producer_cpu = -1;
};

struct FeedClientConfig {
    std::uint16_t port = 9000;
    int connect_timeout_ms = 5000;
    int idle_timeout_ms = 5000;
    int producer_cpu = -1;
    int consumer_cpu = -1;
    std::uint32_t consumer_delay_us = 0; // controlled backpressure experiments only
};

struct ServerResult {
    std::uint64_t sent_messages = 0;
    std::uint64_t price_updates = 0;
    std::uint64_t bytes = 0;
    double elapsed_seconds = 0.0;
    FeedError error = FeedError::None;
    int system_error = 0;
    const char* operation = "none";
    bool stopped = false;
};

struct FeedResult {
    std::uint64_t decoded_messages = 0;
    std::uint64_t processed_messages = 0;
    std::uint64_t price_updates = 0;
    std::uint64_t bytes = 0;
    // Counts failed try_push attempts, including retries of the same message.
    std::uint64_t queue_full_events = 0;
    std::uint64_t decode_errors = 0;
    // Frames with missing or unordered monotonic stamps skip all latency samples.
    std::uint64_t invalid_timestamps = 0;
    std::uint64_t sequence_gaps = 0;
    std::uint64_t duplicates = 0;
    std::uint64_t out_of_order = 0;
    double elapsed_seconds = 0.0;
    LatencyHistogram transport_latency;
    LatencyHistogram queue_latency;
    LatencyHistogram processing_latency;
    LatencyHistogram end_to_end_latency;
    FeedError error = FeedError::None;
    int system_error = 0;
    const char* operation = "none";
    ProtocolError protocol_error = ProtocolError::None;
    bool stopped = false;
};

// One accepted connection per invocation. No external address is accepted.
// Frames: SnapshotStart, Heartbeat, N PriceUpdates, SnapshotEnd; sequences start 0.
[[nodiscard]] ServerResult run_feed_server(LoopbackListener& listener,
    const FeedServerConfig& config, std::stop_token stop = {});

// Creates exactly one network producer and one processing consumer (jthreads).
// The callback belongs to the consumer only and must not throw. Valid frames wait
// losslessly when the fixed SPSC queue is full. Stop ends network production and
// drains already queued messages unless the consumer rejects a message.
[[nodiscard]] FeedResult run_feed_client(const FeedClientConfig& config,
    MessageConsumer consumer, void* context, std::stop_token stop = {});

} // namespace etf_genome::network
