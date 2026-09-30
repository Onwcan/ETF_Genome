#pragma once

#include <cstdint>
#include <type_traits>

namespace etf_genome {

enum class MessageType : std::uint16_t {
    Heartbeat = 1,
    PriceUpdate = 2,
    Trade = 3,
    SnapshotStart = 4,
    SnapshotEnd = 5,
};

// Runtime representation only: its padding and layout are never sent over the wire.
struct MarketMessage {
    MessageType type = MessageType::Heartbeat;
    std::uint64_t sequence = 0;
    std::uint64_t send_timestamp_ns = 0;
    std::uint64_t decoded_timestamp_ns = 0;
    std::uint32_t instrument_id = 0;
    std::int64_t price_ticks = 0;
    std::uint32_t quantity = 0;
    std::uint32_t instrument_count = 0;
};

static_assert(std::is_trivially_copyable_v<MarketMessage>);
static_assert(std::is_standard_layout_v<MarketMessage>);

} // namespace etf_genome
