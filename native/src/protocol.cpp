#include "etf_genome/market/protocol.hpp"

#include <bit>

namespace etf_genome {
namespace {

constexpr std::array<std::byte, 4> magic{std::byte{'E'}, std::byte{'G'}, std::byte{'M'},
                                         std::byte{'D'}};

template <typename Unsigned>
void write_big_endian(std::byte* destination, Unsigned value) noexcept {
    for (std::size_t index = 0; index < sizeof(Unsigned); ++index) {
        const auto shift = static_cast<unsigned>((sizeof(Unsigned) - index - 1) * 8);
        destination[index] = static_cast<std::byte>((value >> shift) & Unsigned{0xff});
    }
}

template <typename Unsigned>
Unsigned read_big_endian(const std::byte* source) noexcept {
    Unsigned value = 0;
    for (std::size_t index = 0; index < sizeof(Unsigned); ++index) {
        value = static_cast<Unsigned>((value << 8U) | std::to_integer<unsigned>(source[index]));
    }
    return value;
}

bool payload_size(MessageType type, std::uint32_t& size) noexcept {
    switch (type) {
    case MessageType::Heartbeat:
    case MessageType::SnapshotEnd: size = 0; return true;
    case MessageType::PriceUpdate:
    case MessageType::Trade: size = 16; return true;
    case MessageType::SnapshotStart: size = 4; return true;
    }
    return false;
}

} // namespace

const char* protocol_error_name(ProtocolError error) noexcept {
    switch (error) {
    case ProtocolError::None: return "none";
    case ProtocolError::BadMagic: return "bad magic";
    case ProtocolError::UnsupportedVersion: return "unsupported version";
    case ProtocolError::UnknownType: return "unknown message type";
    case ProtocolError::InvalidLength: return "invalid frame length";
    case ProtocolError::NonzeroReserved: return "nonzero reserved field";
    case ProtocolError::TruncatedFrame: return "EOF with partial frame";
    case ProtocolError::SinkStopped: return "message sink stopped";
    case ProtocolError::InvalidSink: return "null message sink";
    }
    return "unknown protocol error";
}

ProtocolError encode_message(const MarketMessage& message, EncodedFrame& output) noexcept {
    std::uint32_t length = 0;
    if (!payload_size(message.type, length)) {
        return ProtocolError::UnknownType;
    }
    output.bytes.fill(std::byte{0});
    for (std::size_t index = 0; index < magic.size(); ++index) {
        output.bytes[index] = magic[index];
    }
    write_big_endian(output.bytes.data() + 4, protocol_version);
    write_big_endian(output.bytes.data() + 6, static_cast<std::uint16_t>(message.type));
    write_big_endian(output.bytes.data() + 8, length);
    write_big_endian(output.bytes.data() + 16, message.sequence);
    write_big_endian(output.bytes.data() + 24, message.send_timestamp_ns);
    if (message.type == MessageType::PriceUpdate || message.type == MessageType::Trade) {
        write_big_endian(output.bytes.data() + 32, message.instrument_id);
        write_big_endian(output.bytes.data() + 36, std::bit_cast<std::uint64_t>(message.price_ticks));
        write_big_endian(output.bytes.data() + 44, message.quantity);
    } else if (message.type == MessageType::SnapshotStart) {
        write_big_endian(output.bytes.data() + 32, message.instrument_count);
    }
    output.size = protocol_header_size + static_cast<std::size_t>(length);
    return ProtocolError::None;
}

ProtocolError decode_header(std::span<const std::byte> bytes, FrameHeader& output) noexcept {
    if (bytes.size() != protocol_header_size) {
        return ProtocolError::InvalidLength;
    }
    for (std::size_t index = 0; index < magic.size(); ++index) {
        if (bytes[index] != magic[index]) {
            return ProtocolError::BadMagic;
        }
    }
    if (read_big_endian<std::uint16_t>(bytes.data() + 4) != protocol_version) {
        return ProtocolError::UnsupportedVersion;
    }
    FrameHeader header;
    header.type = static_cast<MessageType>(read_big_endian<std::uint16_t>(bytes.data() + 6));
    std::uint32_t expected = 0;
    if (!payload_size(header.type, expected)) {
        return ProtocolError::UnknownType;
    }
    header.payload_length = read_big_endian<std::uint32_t>(bytes.data() + 8);
    if (header.payload_length != expected ||
        header.payload_length > protocol_max_frame_size - protocol_header_size) {
        return ProtocolError::InvalidLength;
    }
    if (read_big_endian<std::uint32_t>(bytes.data() + 12) != 0) {
        return ProtocolError::NonzeroReserved;
    }
    header.sequence = read_big_endian<std::uint64_t>(bytes.data() + 16);
    header.send_timestamp_ns = read_big_endian<std::uint64_t>(bytes.data() + 24);
    output = header;
    return ProtocolError::None;
}

ProtocolError decode_frame(std::span<const std::byte> bytes, MarketMessage& output) noexcept {
    if (bytes.size() < protocol_header_size || bytes.size() > protocol_max_frame_size) {
        return ProtocolError::InvalidLength;
    }
    FrameHeader header;
    const auto error = decode_header(bytes.first(protocol_header_size), header);
    if (error != ProtocolError::None) {
        return error;
    }
    if (bytes.size() != protocol_header_size + header.payload_length) {
        return ProtocolError::InvalidLength;
    }
    MarketMessage message;
    message.type = header.type;
    message.sequence = header.sequence;
    message.send_timestamp_ns = header.send_timestamp_ns;
    if (message.type == MessageType::PriceUpdate || message.type == MessageType::Trade) {
        message.instrument_id = read_big_endian<std::uint32_t>(bytes.data() + 32);
        message.price_ticks = std::bit_cast<std::int64_t>(
            read_big_endian<std::uint64_t>(bytes.data() + 36));
        message.quantity = read_big_endian<std::uint32_t>(bytes.data() + 44);
    } else if (message.type == MessageType::SnapshotStart) {
        message.instrument_count = read_big_endian<std::uint32_t>(bytes.data() + 32);
    }
    output = message;
    return ProtocolError::None;
}

} // namespace etf_genome
