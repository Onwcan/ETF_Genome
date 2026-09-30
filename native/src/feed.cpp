#include "etf_genome/network/feed.hpp"

#include "etf_genome/core/clock.hpp"
#include "etf_genome/market/decoder.hpp"
#include "etf_genome/metrics/sequence.hpp"
#include "etf_genome/network/epoll.hpp"
#include "etf_genome/spsc_queue.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <limits>
#include <mutex>
#include <new>
#include <span>
#include <sys/socket.h>
#include <thread>

namespace etf_genome::network {
namespace {
using Clock = std::chrono::steady_clock;
constexpr auto wake_interval = std::chrono::milliseconds(50);
constexpr std::size_t read_budget = 32;

void record_system(ServerResult& result, FeedError error, int code, const char* operation) noexcept {
    result.error = error;
    result.system_error = code;
    result.operation = operation;
}

bool wait_until(Clock::time_point deadline, std::stop_token stop) {
    // Pacing is approximate, uses steady time and checks shutdown every 50ms.
    while (!stop.stop_requested() && Clock::now() < deadline) {
        std::this_thread::sleep_until(std::min(deadline, Clock::now() + wake_interval));
    }
    return !stop.stop_requested();
}

bool send_frame(int socket, Epoll& events, const EncodedFrame& frame,
                const FeedServerConfig& config, std::stop_token stop, ServerResult& result) {
    std::size_t offset = 0;
    auto last_progress = Clock::now();
    std::array<epoll_event, 1> ready{};
    while (offset < frame.size && !stop.stop_requested()) {
        const auto length = std::min(frame.size - offset, config.send_chunk_bytes);
        const auto sent = ::send(socket, frame.bytes.data() + offset, length, MSG_NOSIGNAL);
        if (sent > 0) {
            offset += static_cast<std::size_t>(sent);
            result.bytes += static_cast<std::uint64_t>(sent);
            last_progress = Clock::now();
            continue;
        }
        if (sent < 0 && errno == EINTR) continue;
        if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            if (Clock::now() - last_progress >= std::chrono::milliseconds(config.idle_timeout_ms)) {
                record_system(result, FeedError::Timeout, ETIMEDOUT, "send progress deadline");
                return false;
            }
            if (events.wait(ready, static_cast<int>(wake_interval.count())) < 0) {
                record_system(result, FeedError::System, errno, "epoll_wait send");
                return false;
            }
            continue;
        }
        const auto code = sent == 0 ? EPIPE : errno;
        record_system(result, code == EPIPE || code == ECONNRESET ? FeedError::PeerDisconnected
                                                                 : FeedError::System,
                      code, "send");
        return false;
    }
    if (stop.stop_requested()) {
        result.stopped = true;
        return false;
    }
    ++result.sent_messages;
    return true;
}

struct Pipeline {
    SpscQueue<MarketMessage, feed_queue_capacity> queue;
    std::mutex wait_mutex;
    std::condition_variable available;
    std::atomic<bool> producer_done{false};
    std::stop_source shutdown;
    FeedResult producer_result;
    FeedResult consumer_result;
    SequenceTracker sequences;
};

bool enqueue(void* context, const MarketMessage& message) noexcept {
    auto& pipeline = *static_cast<Pipeline*>(context);
    while (!pipeline.shutdown.stop_requested()) {
        if (pipeline.queue.try_push(message)) {
            ++pipeline.producer_result.decoded_messages;
            pipeline.sequences.observe(message.sequence);
            pipeline.available.notify_one();
            return true;
        }
        ++pipeline.producer_result.queue_full_events;
        std::unique_lock lock(pipeline.wait_mutex);
        // Bounded sleeping avoids a hot spin; notifications usually wake sooner.
        pipeline.available.wait_for(lock, std::chrono::milliseconds(1));
    }
    return false;
}

void producer_loop(Pipeline& pipeline, int socket, Epoll& events,
                   const FeedClientConfig& config) noexcept {
    auto& result = pipeline.producer_result;
    const auto affinity_error = pin_current_thread(config.producer_cpu);
    if (affinity_error != 0) {
        result.error = FeedError::Affinity;
        result.system_error = affinity_error;
        result.operation = "pthread_setaffinity_np producer";
    } else {
        IncrementalDecoder decoder;
        std::array<std::byte, 16384> bytes{};
        std::array<epoll_event, 1> ready{};
        auto last_read = Clock::now();
        bool done = false;
        while (!done && !pipeline.shutdown.stop_requested()) {
            const auto count = events.wait(ready, static_cast<int>(wake_interval.count()));
            if (count < 0) {
                result.error = FeedError::System;
                result.system_error = errno;
                result.operation = "epoll_wait receive";
                break;
            }
            if (count == 0) {
                if (Clock::now() - last_read >= std::chrono::milliseconds(config.idle_timeout_ms)) {
                    result.error = FeedError::Timeout;
                    result.system_error = ETIMEDOUT;
                    result.operation = "receive idle deadline";
                    break;
                }
                continue;
            }
            // The level-triggered socket remains readable if this budget expires.
            for (std::size_t reads = 0; reads < read_budget && !pipeline.shutdown.stop_requested(); ++reads) {
                const auto received = ::recv(socket, bytes.data(), bytes.size(), 0);
                if (received > 0) {
                    last_read = Clock::now();
                    result.bytes += static_cast<std::uint64_t>(received);
                    const auto decoded = decoder.feed(
                        std::span<const std::byte>(bytes.data(), static_cast<std::size_t>(received)),
                        enqueue, &pipeline);
                    if (decoded.error != ProtocolError::None) {
                        if (decoded.error != ProtocolError::SinkStopped || !pipeline.shutdown.stop_requested()) {
                            result.error = FeedError::Protocol;
                            result.protocol_error = decoded.error;
                            ++result.decode_errors;
                            result.operation = "incremental decoder";
                        }
                        done = true;
                        break;
                    }
                    continue;
                }
                if (received == 0) {
                    const auto error = decoder.finish();
                    if (error != ProtocolError::None) {
                        result.error = FeedError::Protocol;
                        result.protocol_error = error;
                        ++result.decode_errors;
                        result.operation = "decoder EOF";
                    }
                    done = true;
                    break;
                }
                if (errno == EINTR) continue;
                if (errno == EAGAIN || errno == EWOULDBLOCK) break;
                result.error = errno == ECONNRESET ? FeedError::PeerDisconnected : FeedError::System;
                result.system_error = errno;
                result.operation = "recv";
                done = true;
                break;
            }
        }
    }
    pipeline.producer_done.store(true, std::memory_order_release);
    pipeline.available.notify_all();
}

void consumer_loop(Pipeline& pipeline, const FeedClientConfig& config,
                   MessageConsumer consume, void* context) noexcept {
    auto& result = pipeline.consumer_result;
    const auto affinity_error = pin_current_thread(config.consumer_cpu);
    if (affinity_error != 0) {
        result.error = FeedError::Affinity;
        result.system_error = affinity_error;
        result.operation = "pthread_setaffinity_np consumer";
        pipeline.shutdown.request_stop();
        pipeline.available.notify_all();
        return;
    }
    for (;;) {
        MarketMessage message{};
        if (!pipeline.queue.try_pop(message)) {
            if (pipeline.producer_done.load(std::memory_order_acquire)) {
                // The producer may have published between the first pop and done.
                if (!pipeline.queue.try_pop(message)) break;
            } else {
                std::unique_lock lock(pipeline.wait_mutex);
                pipeline.available.wait_for(lock, std::chrono::milliseconds(1));
                continue;
            }
        }
        pipeline.available.notify_one();
        const auto started = monotonic_now_ns();
        if (!consume(context, message)) {
            result.error = FeedError::ConsumerRejected;
            result.operation = "consumer callback";
            pipeline.shutdown.request_stop();
            pipeline.available.notify_all();
            break;
        }
        const auto finished = monotonic_now_ns();
        ++result.processed_messages;
        if (message.type == MessageType::PriceUpdate) ++result.price_updates;
        const auto send = message.send_timestamp_ns;
        const auto decoded = message.decoded_timestamp_ns;
        if (send == 0 || decoded == 0 || started == 0 || finished == 0 ||
            send > decoded || decoded > started || started > finished) {
            ++result.invalid_timestamps;
        } else {
            result.transport_latency.record(decoded - send);
            result.queue_latency.record(started - decoded);
            result.processing_latency.record(finished - started);
            result.end_to_end_latency.record(finished - send);
        }
        if (config.consumer_delay_us != 0) {
            // Test delays also observe shutdown. Draining on stop skips the
            // artificial delay so a large configured delay cannot stall exit.
            (void)wait_until(Clock::now() + std::chrono::microseconds(config.consumer_delay_us),
                             pipeline.shutdown.get_token());
        }
    }
}

} // namespace

const char* feed_error_name(FeedError error) noexcept {
    switch (error) {
    case FeedError::None: return "none";
    case FeedError::System: return "system";
    case FeedError::Timeout: return "timeout";
    case FeedError::PeerDisconnected: return "peer_disconnected";
    case FeedError::Protocol: return "protocol";
    case FeedError::ConsumerRejected: return "consumer_rejected";
    case FeedError::Affinity: return "affinity";
    }
    return "unknown";
}

ServerResult run_feed_server(LoopbackListener& listener, const FeedServerConfig& config,
                             std::stop_token stop) {
    if (config.instruments == 0 || config.idle_timeout_ms <= 0 || config.send_chunk_bytes == 0 ||
        config.events > std::numeric_limits<std::uint64_t>::max() - 3 ||
        config.rate_per_second > 1000000000ULL)
        throw std::invalid_argument("invalid synthetic feed server configuration");
    ServerResult result;
    const auto started = Clock::now();
    const auto affinity_error = pin_current_thread(config.producer_cpu);
    if (affinity_error != 0) {
        record_system(result, FeedError::Affinity, affinity_error, "pthread_setaffinity_np sender");
        return result;
    }
    Epoll accepts;
    accepts.add(listener.descriptor(), EPOLLIN);
    std::array<epoll_event, 1> ready{};
    UniqueFd client;
    while (!client && !stop.stop_requested()) {
        if (Clock::now() - started >= std::chrono::milliseconds(config.idle_timeout_ms)) {
            record_system(result, FeedError::Timeout, ETIMEDOUT, "accept deadline");
            break;
        }
        if (accepts.wait(ready, static_cast<int>(wake_interval.count())) < 0) {
            record_system(result, FeedError::System, errno, "epoll_wait accept");
            break;
        }
        const auto accepted = accept_nonblocking(listener.descriptor());
        if (accepted >= 0) client.reset(accepted);
        else if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
            record_system(result, FeedError::System, errno, "accept4");
            break;
        }
    }
    if (client && !stop.stop_requested()) {
        Epoll writable;
        writable.add(client.get(), EPOLLOUT | EPOLLRDHUP);
        std::uint64_t sequence = 0;
        auto emit = [&](MarketMessage message) {
            message.sequence = sequence++;
            message.send_timestamp_ns = monotonic_now_ns();
            EncodedFrame frame;
            const auto error = encode_message(message, frame);
            if (error != ProtocolError::None) {
                result.error = FeedError::Protocol;
                result.operation = "encode synthetic frame";
                return false;
            }
            return send_frame(client.get(), writable, frame, config, stop, result);
        };
        MarketMessage first{};
        first.type = MessageType::SnapshotStart;
        first.instrument_count = config.instruments;
        bool healthy = emit(first);
        MarketMessage heartbeat{};
        heartbeat.type = MessageType::Heartbeat;
        if (healthy) healthy = emit(heartbeat);
        auto next_send = Clock::now();
        const auto period = std::chrono::nanoseconds(config.rate_per_second == 0 ? 0 :
            static_cast<std::int64_t>(1000000000ULL / config.rate_per_second));
        std::uint32_t state = config.seed;
        for (std::uint64_t index = 0; healthy && index < config.events; ++index) {
            if (config.rate_per_second != 0) {
                healthy = wait_until(next_send, stop);
                if (!healthy) break;
                next_send += period;
            }
            state = state * 1664525U + 1013904223U;
            MarketMessage message{};
            message.type = MessageType::PriceUpdate;
            message.instrument_id = static_cast<std::uint32_t>(index % config.instruments);
            message.price_ticks = 1000000 + static_cast<std::int64_t>(message.instrument_id) * 100 +
                                  static_cast<std::int64_t>(state % 2001U) - 1000;
            message.quantity = state % 100U + 1U;
            healthy = emit(message);
            if (healthy) ++result.price_updates;
        }
        if (healthy) {
            MarketMessage last{};
            last.type = MessageType::SnapshotEnd;
            (void)emit(last);
        }
        // Closing the RAII socket supplies EOF; queued TCP bytes remain readable.
    }
    result.stopped = result.stopped || stop.stop_requested();
    result.elapsed_seconds = std::chrono::duration<double>(Clock::now() - started).count();
    return result;
}

FeedResult run_feed_client(const FeedClientConfig& config, MessageConsumer consumer,
                           void* context, std::stop_token stop) {
    if (consumer == nullptr || config.idle_timeout_ms <= 0)
        throw std::invalid_argument("feed client requires a callback and positive idle timeout");
    const auto started = Clock::now();
    if (stop.stop_requested()) {
        FeedResult result;
        result.stopped = true;
        return result;
    }
    UniqueFd socket;
    try {
        socket = connect_loopback(config.port, config.connect_timeout_ms, stop);
    } catch (const SocketError& error) {
        if (error.code() != ECANCELED || !stop.stop_requested()) throw;
        FeedResult result;
        result.stopped = true;
        result.elapsed_seconds = std::chrono::duration<double>(Clock::now() - started).count();
        return result;
    }
    Epoll events;
    events.add(socket.get(), EPOLLIN | EPOLLRDHUP);
    Pipeline pipeline;
    std::stop_callback bridge(stop, [&] {
        pipeline.shutdown.request_stop();
        pipeline.available.notify_all();
    });
    std::jthread producer([&] { producer_loop(pipeline, socket.get(), events, config); });
    // If thread construction throws, stop and join the already running producer.
    std::jthread consumer_thread;
    try {
        consumer_thread = std::jthread([&] { consumer_loop(pipeline, config, consumer, context); });
    } catch (const std::system_error&) {
        pipeline.shutdown.request_stop();
        pipeline.available.notify_all();
        producer.join();
        throw;
    } catch (const std::bad_alloc&) {
        // Thread startup may also fail allocating its control state. The network
        // loop uses the shared source, so jthread's own stop token is insufficient.
        pipeline.shutdown.request_stop();
        pipeline.available.notify_all();
        producer.join();
        throw;
    }
    producer.join();
    consumer_thread.join();
    auto result = std::move(pipeline.consumer_result);
    const auto& produced = pipeline.producer_result;
    result.decoded_messages = produced.decoded_messages;
    result.bytes = produced.bytes;
    result.queue_full_events = produced.queue_full_events;
    result.decode_errors = produced.decode_errors;
    result.protocol_error = produced.protocol_error;
    if (result.error == FeedError::None) {
        result.error = produced.error;
        result.system_error = produced.system_error;
        result.operation = produced.operation;
    }
    const auto& sequences = pipeline.sequences.counters();
    result.sequence_gaps = sequences.gaps;
    result.duplicates = sequences.duplicates;
    result.out_of_order = sequences.out_of_order;
    result.stopped = stop.stop_requested();
    result.elapsed_seconds = std::chrono::duration<double>(Clock::now() - started).count();
    return result;
}

} // namespace etf_genome::network
