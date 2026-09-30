#include "etf_genome/market/protocol.hpp"
#include "etf_genome/core/clock.hpp"
#include "etf_genome/network/epoll.hpp"
#include "etf_genome/network/feed.hpp"

#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstddef>
#include <exception>
#include <fcntl.h>
#include <iostream>
#include <limits>
#include <poll.h>
#include <span>
#include <stdexcept>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <utility>

namespace {
using namespace etf_genome;
using namespace etf_genome::network;
int checks = 0;

void check(bool condition, const char* message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}

struct Collected {
    std::uint64_t frames = 0;
    std::uint64_t prices = 0;
    std::uint64_t last_sequence = 0;
    std::uint64_t checksum = 0;
};
bool collect(void* context, const MarketMessage& message) noexcept {
    auto& collected = *static_cast<Collected*>(context);
    ++collected.frames;
    collected.last_sequence = message.sequence;
    if (message.type == MessageType::PriceUpdate) {
        ++collected.prices;
        collected.checksum += static_cast<std::uint64_t>(message.price_ticks);
    }
    return true;
}
bool reject(void*, const MarketMessage&) noexcept { return false; }

std::uint64_t expected_checksum(std::uint64_t events, std::uint32_t instruments, std::uint32_t seed) {
    std::uint64_t sum = 0;
    auto state = seed;
    for (std::uint64_t index = 0; index < events; ++index) {
        state = state * 1664525U + 1013904223U;
        const auto price = 1000000 + static_cast<std::int64_t>(index % instruments) * 100 +
                           static_cast<std::int64_t>(state % 2001U) - 1000;
        sum += static_cast<std::uint64_t>(price);
    }
    return sum;
}

void descriptors_and_affinity() {
    auto listener = listen_loopback(0);
    check(listener.port() != 0, "ephemeral listener has a usable port");
    check((::fcntl(listener.descriptor(), F_GETFL) & O_NONBLOCK) != 0, "listener is nonblocking");
    check((::fcntl(listener.descriptor(), F_GETFD) & FD_CLOEXEC) != 0, "listener is close-on-exec");
    std::array<int, 2> pipe{};
    check(::pipe2(pipe.data(), O_NONBLOCK | O_CLOEXEC) == 0, "create descriptor ownership fixture");
    UniqueFd first(pipe[0]);
    UniqueFd second(std::move(first));
    UniqueFd writer(pipe[1]);
    check(!first && second.get() == pipe[0], "moving descriptor transfers ownership");
    first = std::move(second);
    check(!second && first.get() == pipe[0], "move assignment transfers ownership");
    first.reset();
    check(::fcntl(pipe[0], F_GETFD) == -1 && errno == EBADF, "descriptor closes exactly once");
    check(pin_current_thread(-1) == 0, "affinity is disabled by default");
    check(pin_current_thread(-2) == EINVAL && pin_current_thread(100000) == EINVAL,
          "affinity rejects invalid requested CPUs");
}

void synthetic_pipeline(std::size_t chunk, std::uint32_t delay, std::uint64_t events) {
    auto listener = listen_loopback(0);
    FeedServerConfig server_config;
    server_config.events = events;
    server_config.instruments = 17;
    server_config.seed = 123;
    server_config.send_chunk_bytes = chunk;
    ServerResult sent;
    std::exception_ptr server_failure;
    std::jthread server([&](std::stop_token stop) {
        try { sent = run_feed_server(listener, server_config, stop); }
        catch (const std::exception&) { server_failure = std::current_exception(); }
    });
    FeedClientConfig config;
    config.port = listener.port();
    config.consumer_delay_us = delay;
    Collected collected;
    const auto result = run_feed_client(config, collect, &collected);
    server.join();
    if (server_failure) std::rethrow_exception(server_failure);
    check(sent.error == FeedError::None && result.error == FeedError::None, "loopback pipeline succeeds");
    check(sent.price_updates == events && collected.prices == events && result.price_updates == events,
          "all synthetic prices are processed once");
    check(sent.sent_messages == events + 3 && result.decoded_messages == events + 3 &&
          result.processed_messages == events + 3, "snapshot and heartbeat frames are counted");
    check(collected.last_sequence == events + 2 && result.sequence_gaps == 0 && result.duplicates == 0 &&
          result.out_of_order == 0, "synthetic sequence is continuous from zero");
    check(sent.bytes == result.bytes, "TCP byte accounting agrees with sender");
    check(collected.checksum == expected_checksum(events, 17, 123), "seeded prices are deterministic");
    check(result.end_to_end_latency.count() == events + 3 &&
          result.processing_latency.count() == events + 3 && result.invalid_timestamps == 0,
          "each valid processed frame has latency samples");
    if (delay != 0) check(result.queue_full_events > 0, "slow consumer exercises lossless queue backpressure");
}

// Tests use the same loopback endpoint, and all waits have a finite deadline.
UniqueFd accept_fixture(LoopbackListener& listener, std::stop_token stop) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (!stop.stop_requested() && std::chrono::steady_clock::now() < deadline) {
        const auto socket = accept_nonblocking(listener.descriptor());
        if (socket >= 0) return UniqueFd(socket);
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            throw SocketError("accept fixture", errno, "loopback test");
        pollfd ready{listener.descriptor(), POLLIN, 0};
        if (::poll(&ready, 1, 20) < 0 && errno != EINTR)
            throw SocketError("poll fixture", errno, "loopback test");
    }
    throw std::runtime_error("test accept deadline");
}

void write_fixture(int socket, std::span<const std::byte> bytes, std::stop_token stop) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    std::size_t offset = 0;
    while (offset < bytes.size() && !stop.stop_requested()) {
        if (std::chrono::steady_clock::now() >= deadline) throw std::runtime_error("test send deadline");
        const auto count = ::send(socket, bytes.data() + offset, bytes.size() - offset, MSG_NOSIGNAL);
        if (count > 0) offset += static_cast<std::size_t>(count);
        else if (count < 0 && errno == EINTR) continue;
        else if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            pollfd ready{socket, POLLOUT, 0};
            (void)::poll(&ready, 1, 20);
        } else throw SocketError("send fixture", errno, "loopback test");
    }
}

template <typename Send>
FeedResult fixture_pipeline(Send send) {
    auto listener = listen_loopback(0);
    std::exception_ptr failure;
    std::jthread server([&](std::stop_token stop) {
        try {
            auto socket = accept_fixture(listener, stop);
            send(socket.get(), stop);
        } catch (const std::exception&) { failure = std::current_exception(); }
    });
    FeedClientConfig config;
    config.port = listener.port();
    config.idle_timeout_ms = 100;
    Collected collected;
    const auto result = run_feed_client(config, collect, &collected);
    server.join();
    if (failure) std::rethrow_exception(failure);
    return result;
}

void malformed_and_sequence() {
    const auto partial = fixture_pipeline([](int socket, std::stop_token stop) {
        MarketMessage message{};
        message.type = MessageType::PriceUpdate;
        message.price_ticks = 100;
        EncodedFrame frame;
        if (encode_message(message, frame) != ProtocolError::None) throw std::runtime_error("encode fixture");
        write_fixture(socket, frame.view().first(frame.size - 1), stop);
    });
    check(partial.error == FeedError::Protocol && partial.protocol_error == ProtocolError::TruncatedFrame &&
          partial.decode_errors == 1 && partial.processed_messages == 0,
          "EOF with partial payload reports truncated frame");

    const auto corrupt = fixture_pipeline([](int socket, std::stop_token stop) {
        MarketMessage message{};
        message.type = MessageType::Heartbeat;
        EncodedFrame frame;
        if (encode_message(message, frame) != ProtocolError::None) throw std::runtime_error("encode fixture");
        frame.bytes[0] = std::byte{0};
        write_fixture(socket, frame.view(), stop);
    });
    check(corrupt.error == FeedError::Protocol && corrupt.protocol_error == ProtocolError::BadMagic &&
          corrupt.decode_errors == 1, "corrupt frame reports protocol category");

    const auto sequence = fixture_pipeline([](int socket, std::stop_token stop) {
        for (const auto sequence_number : {0ULL, 2ULL, 2ULL, 1ULL}) {
            MarketMessage message{};
            message.type = MessageType::Heartbeat;
            message.sequence = sequence_number;
            EncodedFrame frame;
            if (encode_message(message, frame) != ProtocolError::None) throw std::runtime_error("encode fixture");
            write_fixture(socket, frame.view(), stop);
        }
    });
    check(sequence.error == FeedError::None && sequence.processed_messages == 4 &&
          sequence.sequence_gaps == 1 && sequence.duplicates == 1 && sequence.out_of_order == 1,
          "network pipeline reports gaps, duplicate high-water and out-of-order sequence");

    const auto idle = fixture_pipeline([](int, std::stop_token) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    });
    check(idle.error == FeedError::Timeout && idle.system_error == ETIMEDOUT,
          "quiet connection reaches bounded idle timeout");
}

void timestamp_validation() {
    const auto result = fixture_pipeline([](int socket, std::stop_token stop) {
        for (std::uint64_t sequence = 0; sequence < 3; ++sequence) {
            MarketMessage message{};
            message.type = MessageType::Heartbeat;
            message.sequence = sequence;
            message.send_timestamp_ns = sequence == 0 ? 0 : sequence == 1
                ? std::numeric_limits<std::uint64_t>::max() : monotonic_now_ns();
            EncodedFrame frame;
            if (encode_message(message, frame) != ProtocolError::None) throw std::runtime_error("encode fixture");
            write_fixture(socket, frame.view(), stop);
        }
    });
    check(result.error == FeedError::None && result.processed_messages == 3 &&
          result.invalid_timestamps == 2, "zero and future send stamps are counted once per processed frame");
    check(result.transport_latency.count() == 1 && result.queue_latency.count() == 1 &&
          result.processing_latency.count() == 1 && result.end_to_end_latency.count() == 1,
          "invalid timestamps do not pollute any latency histogram");
}

void shutdown_disconnect_and_rejection() {
    {
        std::stop_source stop;
        stop.request_stop();
        FeedClientConfig client;
        Collected collected;
        const auto result = run_feed_client(client, collect, &collected, stop.get_token());
        check(result.stopped && result.error == FeedError::None && result.processed_messages == 0,
              "client requested to stop before connecting exits cleanly");
    }
    {
        auto listener = listen_loopback(0);
        FeedServerConfig config;
        config.events = 1000000;
        ServerResult result;
        std::jthread server([&](std::stop_token stop) { result = run_feed_server(listener, config, stop); });
        auto client = connect_loopback(listener.port(), 1000);
        client.reset();
        server.join();
        check(result.error == FeedError::PeerDisconnected, "sender handles disconnected peer without SIGPIPE");
    }
    {
        auto listener = listen_loopback(0);
        FeedServerConfig config;
        config.events = 1000000;
        std::jthread server([&](std::stop_token stop) { (void)run_feed_server(listener, config, stop); });
        FeedClientConfig client;
        client.port = listener.port();
        const auto rejected = run_feed_client(client, reject, nullptr);
        server.request_stop();
        server.join();
        check(rejected.error == FeedError::ConsumerRejected && rejected.processed_messages == 0,
              "consumer rejection stops the producer and joins both threads");
    }
    {
        auto listener = listen_loopback(0);
        FeedServerConfig config;
        config.events = 1000000;
        std::jthread server([&](std::stop_token stop) { (void)run_feed_server(listener, config, stop); });
        std::stop_source stop;
        std::jthread controller([&] {
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
            stop.request_stop();
        });
        FeedClientConfig client;
        client.port = listener.port();
        client.consumer_delay_us = 100;
        Collected collected;
        const auto stopped = run_feed_client(client, collect, &collected, stop.get_token());
        server.request_stop();
        server.join();
        controller.join();
        check(stopped.stopped && stopped.error == FeedError::None,
              "stop token gracefully ends network production");
        check(stopped.decoded_messages == stopped.processed_messages,
              "controlled stop drains every successfully queued frame");
    }
    {
        auto listener = listen_loopback(0);
        FeedServerConfig config;
        config.idle_timeout_ms = 50;
        const auto result = run_feed_server(listener, config);
        check(result.error == FeedError::Timeout, "unconnected server has bounded accept deadline");
    }
}
} // namespace

int main() {
    try {
        descriptors_and_affinity();
        synthetic_pipeline(64, 0, 10000);
        synthetic_pipeline(1, 0, 300);
        synthetic_pipeline(64, 200, 3000);
        malformed_and_sequence();
        timestamp_validation();
        shutdown_disconnect_and_rejection();
        std::cout << "Passed " << checks << " Linux network checks\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Network test failed: " << error.what() << '\n';
        return 1;
    }
}
