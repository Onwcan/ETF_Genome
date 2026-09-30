#include "etf_genome/replay.hpp"
#include "etf_genome/spsc_queue.hpp"

#include <atomic>
#include <chrono>
#include <limits>
#include <stdexcept>
#include <thread>

namespace etf_genome {
namespace {

using Clock = std::chrono::steady_clock;

void validate_graph(const ExposureGraph& graph) {
    if (graph.security_ids().empty() ||
        graph.security_ids().size() > std::numeric_limits<std::uint32_t>::max()) {
        throw std::invalid_argument("Replay requires a nonempty graph with uint32_t security indices");
    }
}

void consume(const ExposureGraph& graph, const ShockEvent& event, ExposureWorkspace& workspace,
             ReplayResult& result) {
    if (event.sequence != result.events) {
        throw std::runtime_error("Replay sequence mismatch");
    }
    graph.evaluate_one(event.security_index, event.shock, workspace);
    for (const auto& impact : workspace.impacts()) {
        result.checksum += impact.direct_shock;
    }
    ++result.events;
}

} // namespace

ShockEvent synthetic_event(std::uint64_t sequence, std::size_t security_count) {
    if (security_count == 0 || security_count > std::numeric_limits<std::uint32_t>::max()) {
        throw std::invalid_argument("Invalid replay security count");
    }
    // Reduce before multiplying to avoid overflow for large sequence numbers.
    const auto security = ((sequence % security_count) * 17U) % security_count;
    const auto shock_step = static_cast<std::int64_t>(sequence % 201U) - 100;
    return ShockEvent{sequence, static_cast<std::uint32_t>(security),
                      static_cast<double>(shock_step) * 0.0001};
}

ReplayResult replay_single_threaded(const ExposureGraph& graph, std::uint64_t event_count) {
    validate_graph(graph);
    auto workspace = graph.make_workspace();
    ReplayResult result;
    const auto start = Clock::now();
    for (std::uint64_t sequence = 0; sequence < event_count; ++sequence) {
        consume(graph, synthetic_event(sequence, graph.security_ids().size()), workspace, result);
    }
    result.elapsed_seconds = std::chrono::duration<double>(Clock::now() - start).count();
    return result;
}

ReplayResult replay_spsc(const ExposureGraph& graph, std::uint64_t event_count) {
    validate_graph(graph);
    SpscQueue<ShockEvent, 1024> queue;
    auto workspace = graph.make_workspace();
    std::atomic<bool> cancel{false};
    ReplayResult result;
    std::uint64_t producer_retries = 0;
    const auto start = Clock::now();
    // Graph construction, workspace allocation, and queue construction precede the clock.
    // Thread startup, generation, backpressure, evaluation, and checksum are measured.
    std::jthread producer([&] {
        for (std::uint64_t sequence = 0; sequence < event_count; ++sequence) {
            const auto event = synthetic_event(sequence, graph.security_ids().size());
            while (!queue.try_push(event)) {
                if (cancel.load(std::memory_order_acquire)) {
                    return;
                }
                ++producer_retries;
                std::this_thread::yield();
            }
            if (cancel.load(std::memory_order_acquire)) {
                return;
            }
        }
    });
    try {
        ShockEvent event{};
        while (result.events < event_count) {
            if (queue.try_pop(event)) {
                consume(graph, event, workspace, result);
            } else {
                ++result.consumer_retries;
                std::this_thread::yield();
            }
        }
    } catch (...) {
        cancel.store(true, std::memory_order_release);
        producer.join();
        throw;
    }
    producer.join();
    result.producer_retries = producer_retries;
    result.elapsed_seconds = std::chrono::duration<double>(Clock::now() - start).count();
    return result;
}

} // namespace etf_genome
