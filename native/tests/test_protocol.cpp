#include "etf_genome/core/clock.hpp"
#include "etf_genome/market/decoder.hpp"
#include "etf_genome/market/protocol.hpp"
#include "etf_genome/metrics/histogram.hpp"
#include "etf_genome/metrics/sequence.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace etf_genome;
int checks = 0;

void check(bool condition, const std::string& message) {
    ++checks;
    if (!condition) {
        throw std::runtime_error(message);
    }
}

struct Collector {
    std::array<MarketMessage, 16> messages{};
    std::size_t count = 0;
    bool accept = true;
};

bool collect(void* context, const MarketMessage& message) noexcept {
    auto& collector = *static_cast<Collector*>(context);
    if (!collector.accept || collector.count == collector.messages.size()) {
        return false;
    }
    collector.messages[collector.count++] = message;
    return true;
}

MarketMessage sample(MessageType type = MessageType::PriceUpdate) {
    MarketMessage message;
    message.type = type;
    message.sequence = 0x0102030405060708ULL;
    message.send_timestamp_ns = 0x1112131415161718ULL;
    message.decoded_timestamp_ns = 999;
    message.instrument_id = 0x21222324U;
    message.price_ticks = -2;
    message.quantity = 0x31323334U;
    message.instrument_count = 0x41424344U;
    return message;
}

EncodedFrame encoded(const MarketMessage& message) {
    EncodedFrame frame;
    check(encode_message(message, frame) == ProtocolError::None, "Message encodes");
    return frame;
}

void explicit_wire_order() {
    const auto frame = encoded(sample());
    const std::array<unsigned, 48> expected{
        0x45, 0x47, 0x4d, 0x44, 0x00, 0x01, 0x00, 0x02,
        0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x00,
        0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18,
        0x21, 0x22, 0x23, 0x24, 0xff, 0xff, 0xff, 0xff,
        0xff, 0xff, 0xff, 0xfe, 0x31, 0x32, 0x33, 0x34};
    check(frame.size == expected.size(), "Price frame is exactly 48 bytes");
    for (std::size_t index = 0; index < expected.size(); ++index) {
        check(std::to_integer<unsigned>(frame.bytes[index]) == expected[index],
              "Explicit expected big-endian bytes match");
    }
    FrameHeader header;
    check(decode_header(frame.view().first(protocol_header_size), header) == ProtocolError::None,
          "Header decodes independently");
    check(header.type == MessageType::PriceUpdate && header.payload_length == 16 &&
              header.sequence == sample().sequence &&
              header.send_timestamp_ns == sample().send_timestamp_ns,
          "Header widths and values are retained");
    check(decode_header(frame.view().first(31), header) == ProtocolError::InvalidLength,
          "Short header rejected");
    check(decode_header(frame.view(), header) == ProtocolError::InvalidLength,
          "Header parser does not accept trailing payload");
}

void all_message_round_trips() {
    for (const auto type : {MessageType::Heartbeat, MessageType::PriceUpdate, MessageType::Trade,
                           MessageType::SnapshotStart, MessageType::SnapshotEnd}) {
        const auto message = sample(type);
        const auto frame = encoded(message);
        MarketMessage parsed;
        check(decode_frame(frame.view(), parsed) == ProtocolError::None, "Full frame decodes");
        check(parsed.type == type && parsed.sequence == message.sequence &&
                  parsed.send_timestamp_ns == message.send_timestamp_ns &&
                  parsed.decoded_timestamp_ns == 0,
              "Wire fields round trip; decode timestamp is not serialized");
        if (type == MessageType::PriceUpdate || type == MessageType::Trade) {
            check(frame.size == 48 && parsed.instrument_id == message.instrument_id &&
                      parsed.price_ticks == message.price_ticks && parsed.quantity == message.quantity,
                  "Price/trade payload round trips");
        } else if (type == MessageType::SnapshotStart) {
            check(frame.size == 36 && parsed.instrument_count == message.instrument_count,
                  "Snapshot start has a four-byte payload");
        } else {
            check(frame.size == 32 && parsed.instrument_id == 0 && parsed.price_ticks == 0 &&
                      parsed.quantity == 0 && parsed.instrument_count == 0,
                  "Header-only messages clear unused runtime fields");
        }
    }
    for (const auto price : {std::numeric_limits<std::int64_t>::min(), std::int64_t{-1},
                            std::int64_t{0}, std::numeric_limits<std::int64_t>::max()}) {
        auto message = sample();
        message.price_ticks = price;
        message.sequence = std::numeric_limits<std::uint64_t>::max();
        message.quantity = std::numeric_limits<std::uint32_t>::max();
        const auto frame = encoded(message);
        MarketMessage parsed;
        check(decode_frame(frame.view(), parsed) == ProtocolError::None &&
                  parsed.price_ticks == price && parsed.sequence == message.sequence &&
                  parsed.quantity == message.quantity,
              "Signed extremes and unsigned maxima decode without narrowing");
    }
    auto unknown = sample();
    unknown.type = static_cast<MessageType>(65535);
    EncodedFrame output;
    output.size = 17;
    output.bytes[0] = std::byte{42};
    check(encode_message(unknown, output) == ProtocolError::UnknownType && output.size == 17 &&
              output.bytes[0] == std::byte{42},
          "Unknown encode type rejected without changing output");
}

void arbitrary_fragmentation() {
    for (const auto type : {MessageType::Heartbeat, MessageType::PriceUpdate, MessageType::Trade,
                           MessageType::SnapshotStart, MessageType::SnapshotEnd}) {
        const auto frame = encoded(sample(type));
        for (std::size_t split = 0; split <= frame.size; ++split) {
            IncrementalDecoder decoder;
            Collector collector;
            const auto first = decoder.feed(frame.view().first(split), collect, &collector);
            const auto second = decoder.feed(frame.view().subspan(split), collect, &collector);
            check(first.error == ProtocolError::None && second.error == ProtocolError::None &&
                      first.bytes_consumed == split && second.bytes_consumed == frame.size - split,
                  "Every header/payload split consumes exactly its available bytes");
            check(first.frames + second.frames == 1 && collector.count == 1 &&
                      collector.messages[0].sequence == sample().sequence &&
                      collector.messages[0].type == type &&
                      collector.messages[0].decoded_timestamp_ns > 0 &&
                      decoder.finish() == ProtocolError::None && decoder.buffered_bytes() == 0,
                  "Every split delivers exactly one complete message");
        }
        IncrementalDecoder decoder;
        Collector collector;
        for (const auto& byte : frame.view()) {
            const auto result = decoder.feed({&byte, 1}, collect, &collector);
            check(result.error == ProtocolError::None && result.bytes_consumed == 1,
                  "One-byte fragments are accepted");
        }
        check(collector.count == 1 && decoder.finish() == ProtocolError::None,
              "Single-byte fragmentation completes");
    }
}

void coalescing_and_eof() {
    std::vector<std::byte> bytes;
    for (std::uint64_t sequence = 0; sequence < 5; ++sequence) {
        auto message = sample(static_cast<MessageType>(sequence + 1));
        message.sequence = sequence;
        const auto frame = encoded(message);
        bytes.insert(bytes.end(), frame.view().begin(), frame.view().end());
    }
    for (std::size_t chunk = 1; chunk <= 67; ++chunk) {
        IncrementalDecoder decoder;
        Collector collector;
        std::size_t position = 0;
        while (position < bytes.size()) {
            const auto length = std::min(chunk, bytes.size() - position);
            const auto result = decoder.feed({bytes.data() + position, length}, collect, &collector);
            check(result.error == ProtocolError::None && result.bytes_consumed == length,
                  "Mixed coalesced frames and fragments consume exactly");
            position += length;
        }
        check(collector.count == 5 && decoder.finish() == ProtocolError::None,
              "All mixed message types delivered across arbitrary read sizes");
        for (std::size_t index = 0; index < collector.count; ++index) {
            check(collector.messages[index].sequence == index, "Coalescing preserves frame order");
        }
    }
    const auto frame = encoded(sample());
    for (std::size_t prefix = 1; prefix < frame.size; ++prefix) {
        IncrementalDecoder decoder;
        Collector collector;
        const auto result = decoder.feed(frame.view().first(prefix), collect, &collector);
        check(result.error == ProtocolError::None && collector.count == 0 &&
                  decoder.finish() == ProtocolError::TruncatedFrame,
              "EOF detects every incomplete header and payload length");
    }
    IncrementalDecoder empty;
    check(empty.finish() == ProtocolError::None, "Empty stream is a clean EOF");
}

void malformed_frames() {
    const auto original = encoded(sample());
    struct Mutation { std::size_t position; std::byte value; ProtocolError error; };
    const std::array mutations{
        Mutation{0, std::byte{'X'}, ProtocolError::BadMagic},
        Mutation{5, std::byte{2}, ProtocolError::UnsupportedVersion},
        Mutation{6, std::byte{1}, ProtocolError::UnknownType},
        Mutation{7, std::byte{0}, ProtocolError::UnknownType},
        Mutation{8, std::byte{0xff}, ProtocolError::InvalidLength},
        Mutation{11, std::byte{15}, ProtocolError::InvalidLength},
        Mutation{11, std::byte{17}, ProtocolError::InvalidLength},
        Mutation{12, std::byte{1}, ProtocolError::NonzeroReserved},
    };
    for (const auto mutation : mutations) {
        auto malformed = original;
        malformed.bytes[mutation.position] = mutation.value;
        MarketMessage output = sample(MessageType::Trade);
        check(decode_frame(malformed.view(), output) == mutation.error &&
                  output.type == MessageType::Trade,
              "Malformed direct decode returns exact error and preserves output");
        IncrementalDecoder decoder;
        Collector collector;
        const auto result = decoder.feed(malformed.view(), collect, &collector);
        check(result.error == mutation.error && result.bytes_consumed == protocol_header_size &&
                  result.frames == 0 && collector.count == 0,
              "Malformed header rejected before copying its payload");
        const auto retry = decoder.feed(original.view(), collect, &collector);
        check(retry.error == mutation.error && retry.bytes_consumed == 0 &&
                  decoder.finish() == mutation.error,
              "Malformed stream stays failed until explicitly reset");
        decoder.reset();
        check(decoder.feed(original.view(), collect, &collector).frames == 1 && collector.count == 1,
              "Reset permits a fresh connection stream");
    }
    MarketMessage output;
    check(decode_frame(original.view().first(47), output) == ProtocolError::InvalidLength,
          "Direct decode rejects truncated payload");
    check(decode_frame({original.bytes.data(), 49}, output) == ProtocolError::InvalidLength,
          "Direct decode rejects extra trailing byte");
    std::array<std::byte, 65> oversized{};
    check(decode_frame(oversized, output) == ProtocolError::InvalidLength,
          "Direct decode rejects an oversized frame before parsing");
    for (const auto type : {MessageType::Heartbeat, MessageType::SnapshotStart,
                           MessageType::SnapshotEnd}) {
        auto frame = encoded(sample(type));
        frame.bytes[11] = std::byte{16};
        check(decode_frame(frame.view(), output) == ProtocolError::InvalidLength,
              "Known types require their exact payload lengths");
    }
}

void sink_backpressure() {
    auto first_message = sample();
    first_message.sequence = 0;
    auto second_message = sample();
    second_message.sequence = 1;
    const auto first = encoded(first_message);
    const auto second = encoded(second_message);
    std::array<std::byte, 96> bytes{};
    std::copy(first.view().begin(), first.view().end(), bytes.begin());
    std::copy(second.view().begin(), second.view().end(), bytes.begin() + 48);
    IncrementalDecoder decoder;
    Collector collector;
    collector.accept = false;
    const auto stopped = decoder.feed(bytes, collect, &collector);
    check(stopped.error == ProtocolError::SinkStopped && stopped.bytes_consumed == 48 &&
              stopped.frames == 0 && decoder.finish() == ProtocolError::SinkStopped,
          "Stopped sink retains exactly one completed frame, leaving input tail unconsumed");
    const auto still_stopped = decoder.feed(std::span<const std::byte>{bytes}.subspan(48), collect,
                                            &collector);
    check(still_stopped.bytes_consumed == 0 && still_stopped.frames == 0 &&
              still_stopped.error == ProtocolError::SinkStopped,
          "Stopped sink cannot silently discard a pending message");
    collector.accept = true;
    const auto resumed = decoder.feed({}, collect, &collector);
    check(resumed.frames == 1 && resumed.bytes_consumed == 0 && resumed.error == ProtocolError::None,
          "Empty feed retries pending delivery without needing another recv");
    check(decoder.feed(std::span<const std::byte>{bytes}.subspan(48), collect, &collector).frames == 1 &&
              collector.count == 2 && collector.messages[0].sequence == 0 &&
              collector.messages[1].sequence == 1 && decoder.finish() == ProtocolError::None,
          "Backpressure resumes without missing, duplicating or reordering frames");
    decoder.reset();
    const auto null_sink = decoder.feed(first.view(), nullptr, nullptr);
    check(null_sink.error == ProtocolError::InvalidSink && null_sink.bytes_consumed == 0 &&
              decoder.finish() == ProtocolError::None,
          "Null sink is recoverable and consumes no input");
    check(decoder.feed(first.view(), collect, &collector).frames == 1,
          "Valid sink works after null-sink error");
}

struct StreamChecker {
    std::uint64_t received = 0;
    bool valid = true;
};

bool verify_stream(void* context, const MarketMessage& message) noexcept {
    auto& checker = *static_cast<StreamChecker*>(context);
    checker.valid = checker.valid && message.sequence == checker.received &&
                    message.instrument_id == checker.received % 31 &&
                    message.price_ticks == -static_cast<std::int64_t>(checker.received);
    ++checker.received;
    return true;
}

void repeated_stream() {
    std::vector<std::byte> bytes;
    constexpr std::uint64_t count = 4096;
    bytes.reserve(static_cast<std::size_t>(count) * 48);
    for (std::uint64_t sequence = 0; sequence < count; ++sequence) {
        auto message = sample();
        message.sequence = sequence;
        message.instrument_id = static_cast<std::uint32_t>(sequence % 31);
        message.price_ticks = -static_cast<std::int64_t>(sequence);
        const auto frame = encoded(message);
        bytes.insert(bytes.end(), frame.view().begin(), frame.view().end());
    }
    IncrementalDecoder decoder;
    StreamChecker checker;
    std::size_t position = 0;
    std::uint32_t random = 17;
    while (position < bytes.size()) {
        random = random * 1664525U + 1013904223U;
        const auto length = std::min(static_cast<std::size_t>(random % 293 + 1), bytes.size() - position);
        const auto result = decoder.feed({bytes.data() + position, length}, verify_stream, &checker);
        check(result.error == ProtocolError::None && result.bytes_consumed == length,
              "Deterministic mixed read sizes preserve decoder state under repeated use");
        position += length;
    }
    check(checker.valid && checker.received == count && decoder.finish() == ProtocolError::None,
          "4096 events have no loss, duplicates or corruption");
}

void histogram_values() {
    LatencyHistogram histogram;
    check(histogram.count() == 0 && histogram.max() == 0 && histogram.percentile(50) == 0,
          "Empty histogram has zero-valued metrics");
    for (std::uint64_t value = 1; value <= 20; ++value) {
        histogram.record(value);
    }
    check(histogram.count() == 20 && histogram.min() == 1 && histogram.max() == 20,
          "Histogram preserves exact count and extrema");
    check(histogram.percentile(50) == 10 && histogram.percentile(90) == 18 &&
              histogram.percentile(95) == 19 && histogram.percentile(99) == 20 &&
              histogram.percentile(99.9) == 20,
          "Known tiny dataset gives exact nearest-rank p50/p90/p95/p99/p99.9");
    check(histogram.percentile(-1) == 1 && histogram.percentile(101) == 20 &&
              histogram.percentile(std::numeric_limits<double>::quiet_NaN()) == 0,
          "Percentile boundary and NaN semantics are explicit");
    histogram.reset();
    for (const auto value : {std::uint64_t{1023}, std::uint64_t{1024}, std::uint64_t{1087},
                            std::uint64_t{1088}, std::uint64_t{2047}, std::uint64_t{2048},
                            std::numeric_limits<std::uint64_t>::max()}) {
        histogram.record(value);
    }
    check(histogram.percentile(1) == 1023 && histogram.percentile(25) == 1087 &&
              histogram.percentile(50) == 1151 && histogram.percentile(70) == 2047 &&
              histogram.percentile(85) == 2175 &&
              histogram.max() == std::numeric_limits<std::uint64_t>::max(),
          "Logarithmic boundary bins return documented upper bounds without overflow");
    histogram.reset();
    histogram.record(9000000);
    check(histogram.percentile(50) == 9000000 && histogram.min() == 9000000 &&
              histogram.count() == 1 && !histogram.saturated(),
          "Single observation is exact even beyond exact bins");
    histogram.reset();
    histogram.record(0);
    histogram.record(0);
    check(histogram.percentile(99.9) == 0 && histogram.count() == 2,
          "Zero latency is a valid measured sample");
}

void sequence_accounting() {
    SequenceTracker tracker;
    for (const auto sequence : {0ULL, 1ULL, 1ULL, 4ULL, 2ULL, 4ULL, 5ULL}) {
        tracker.observe(sequence);
    }
    const auto counters = tracker.counters();
    check(counters.observations == 7 && counters.gaps == 2 && counters.duplicates == 2 &&
              counters.out_of_order == 1,
          "Sequence tracking distinguishes missing values, high-water duplicates and old arrivals");
    tracker.reset();
    tracker.observe(3);
    tracker.observe(4);
    check(tracker.counters().gaps == 3 && tracker.counters().observations == 2,
          "Synthetic sequence stream is expected to begin at zero");
    tracker.reset();
    tracker.observe(std::numeric_limits<std::uint64_t>::max());
    tracker.observe(std::numeric_limits<std::uint64_t>::max());
    tracker.observe(0);
    check(tracker.counters().gaps == std::numeric_limits<std::uint64_t>::max() &&
              tracker.counters().duplicates == 1 && tracker.counters().out_of_order == 1,
          "Maximum sequence does not accidentally wrap the monotonic contract");
    tracker.reset();
    for (std::uint64_t sequence = 0; sequence < 10000; ++sequence) {
        tracker.observe(sequence);
    }
    check(tracker.counters().observations == 10000 && tracker.counters().gaps == 0 &&
              tracker.counters().duplicates == 0 && tracker.counters().out_of_order == 0,
          "Contiguous synthetic stream has clean counters");
}

void monotonic_clock() {
    const auto first = monotonic_now_ns();
    std::uint64_t previous = first;
    bool valid = first > 0;
    for (std::size_t iteration = 0; iteration < 10000; ++iteration) {
        const auto current = monotonic_now_ns();
        valid = valid && current >= previous;
        previous = current;
    }
    check(valid, "Clock timestamps are positive and nondecreasing");
}

} // namespace

int main() {
    try {
        explicit_wire_order();
        all_message_round_trips();
        arbitrary_fragmentation();
        coalescing_and_eof();
        malformed_frames();
        sink_backpressure();
        repeated_stream();
        histogram_values();
        sequence_accounting();
        monotonic_clock();
        std::cout << "Passed " << checks << " protocol/metrics checks\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Test failed: " << error.what() << '\n';
        return 1;
    }
}
