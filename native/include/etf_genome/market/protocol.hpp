#pragma once

#include "etf_genome/market/message.hpp"

#include <array>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <span>

namespace etf_genome {

static_assert(CHAR_BIT == 8, "The wire protocol requires eight-bit bytes");

inline constexpr std::size_t protocol_header_size = 32;
inline constexpr std::size_t protocol_max_frame_size = 64;
inline constexpr std::uint16_t protocol_version = 1;

enum class ProtocolError {
    None,
    BadMagic,
    UnsupportedVersion,
    UnknownType,
    InvalidLength,
    NonzeroReserved,
    TruncatedFrame,
    SinkStopped,
    InvalidSink,
};

[[nodiscard]] const char* protocol_error_name(ProtocolError error) noexcept;

struct FrameHeader {
    MessageType type = MessageType::Heartbeat;
    std::uint32_t payload_length = 0;
    std::uint64_t sequence = 0;
    std::uint64_t send_timestamp_ns = 0;
};

struct EncodedFrame {
    std::array<std::byte, protocol_max_frame_size> bytes{};
    std::size_t size = 0;

    [[nodiscard]] std::span<const std::byte> view() const noexcept {
        return {bytes.data(), size};
    }
};

// All integer fields are big-endian. No alignment or packed-struct assumptions.
// Header bytes: EGMD[0..3], version[4..5], type[6..7], payload length[8..11],
// reserved zero[12..15], sequence[16..23], monotonic send timestamp[24..31].
[[nodiscard]] ProtocolError encode_message(const MarketMessage& message,
                                          EncodedFrame& output) noexcept;
// Only an exact 32-byte header is accepted. Output is unchanged on failure.
[[nodiscard]] ProtocolError decode_header(std::span<const std::byte> bytes,
                                         FrameHeader& output) noexcept;
// Only an exact complete frame is accepted. Output is unchanged on failure.
// Decoder receive timestamps belong to IncrementalDecoder, not the wire format.
[[nodiscard]] ProtocolError decode_frame(std::span<const std::byte> bytes,
                                        MarketMessage& output) noexcept;

} // namespace etf_genome
