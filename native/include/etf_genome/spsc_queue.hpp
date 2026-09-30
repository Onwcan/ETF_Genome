#pragma once

#include "etf_genome/concurrency/cacheline.hpp"

#include <array>
#include <atomic>
#include <cstddef>
#include <limits>
#include <type_traits>

namespace etf_genome {

// Exactly one thread calls try_push; exactly one other thread calls try_pop.
// Failed operations return immediately. The caller owns its backpressure policy.
template <typename T, std::size_t Capacity>
class SpscQueue {
    static_assert(Capacity > 0 && Capacity < std::numeric_limits<std::size_t>::max(),
                  "Capacity must be positive and leave room for the sentinel slot");
    static_assert(std::is_trivially_copyable<T>::value && std::is_nothrow_copy_assignable<T>::value,
                  "Queue elements must have nonthrowing, trivial value semantics");
    static_assert(std::atomic<std::size_t>::is_always_lock_free,
                  "This example requires lock-free size_t atomics on the target");

public:
    SpscQueue() = default;
    SpscQueue(const SpscQueue&) = delete;
    SpscQueue& operator=(const SpscQueue&) = delete;
    [[nodiscard]] static constexpr std::size_t capacity() noexcept { return Capacity; }

    [[nodiscard]] bool try_push(const T& value) noexcept {
        const auto write = producer_.index.load(std::memory_order_relaxed);
        const auto next = advance(write);
        if (next == producer_.cached_read) {
            producer_.cached_read = consumer_.index.load(std::memory_order_acquire);
            if (next == producer_.cached_read) {
                return false;
            }
        }
        slots_[write] = value;
        // Payload writes happen before a consumer's acquire of this publication.
        producer_.index.store(next, std::memory_order_release);
        return true;
    }

    [[nodiscard]] bool try_pop(T& value) noexcept {
        const auto read = consumer_.index.load(std::memory_order_relaxed);
        if (read == consumer_.cached_write) {
            consumer_.cached_write = producer_.index.load(std::memory_order_acquire);
            if (read == consumer_.cached_write) {
                return false;
            }
        }
        value = slots_[read];
        // Completed reads happen before a producer's acquire permits slot reuse.
        consumer_.index.store(advance(read), std::memory_order_release);
        return true;
    }

private:
    static constexpr std::size_t advance(std::size_t index) noexcept {
        return index == Capacity ? 0 : index + 1;
    }

#if defined(_MSC_VER)
    // Cache-line padding of these two hot states is intentional. Keep C4324
    // enabled for every other project type and preserve the queue's alignment.
#pragma warning(push)
#pragma warning(disable : 4324)
#endif
    struct alignas(cacheline_bytes) ProducerState {
        std::atomic<std::size_t> index{0};
        std::size_t cached_read = 0;
    } producer_;
    struct alignas(cacheline_bytes) ConsumerState {
        std::atomic<std::size_t> index{0};
        std::size_t cached_write = 0;
    } consumer_;
#if defined(_MSC_VER)
#pragma warning(pop)
#endif
    alignas(cacheline_bytes) std::array<T, Capacity + 1> slots_{};
};

} // namespace etf_genome
