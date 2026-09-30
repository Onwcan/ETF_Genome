#pragma once

#include "etf_genome/market/protocol.hpp"

#include <array>
#include <cstddef>
#include <span>

namespace etf_genome {

using MessageSink = bool (*)(void*, const MarketMessage&) noexcept;

struct DecodeResult {
    std::size_t bytes_consumed = 0;
    std::size_t frames = 0; // Successfully accepted by the sink in this call.
    ProtocolError error = ProtocolError::None;
};

class IncrementalDecoder {
public:
    // Handles any fragmentation/coalescing. Protocol errors are sticky until reset.
    // A false sink result retains the completed message and returns SinkStopped;
    // no subsequent input is consumed. Retry delivery with feed({}, sink, context).
    // The caller owns the unconsumed tail, based on bytes_consumed.
    [[nodiscard]] DecodeResult feed(std::span<const std::byte> bytes, MessageSink sink,
                                    void* context) noexcept;
    // EOF is clean only with no partial or undelivered frame. This does not reset.
    [[nodiscard]] ProtocolError finish() const noexcept;
    void reset() noexcept;
    [[nodiscard]] std::size_t buffered_bytes() const noexcept { return used_; }

private:
    std::array<std::byte, protocol_max_frame_size> buffer_{};
    std::size_t used_ = 0;
    std::size_t target_ = protocol_header_size;
    bool header_valid_ = false;
    bool ready_ = false;
    MarketMessage pending_{};
    ProtocolError error_ = ProtocolError::None;
};

} // namespace etf_genome
