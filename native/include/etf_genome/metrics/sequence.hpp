#pragma once

#include <cstdint>
#include <limits>

namespace etf_genome {

struct SequenceCounters {
    std::uint64_t observations = 0;
    std::uint64_t gaps = 0; // Missing sequence values, not the number of gap events.
    std::uint64_t duplicates = 0;
    std::uint64_t out_of_order = 0;
};

class SequenceTracker {
public:
    // Synthetic streams start at zero and do not wrap. Duplicate means a repeat
    // of the high-water sequence; older repeated values count as out-of-order.
    // Arbitrary historical duplicate detection would require unbounded history.
    void observe(std::uint64_t sequence) noexcept {
        increment(counters_.observations);
        if (observed_ && sequence == high_water_) {
            increment(counters_.duplicates);
            return;
        }
        if (observed_ && sequence < high_water_) {
            increment(counters_.out_of_order);
            return;
        }
        const auto expected = observed_ ? high_water_ + 1 : 0;
        add(counters_.gaps, sequence - expected);
        high_water_ = sequence;
        observed_ = true;
    }

    [[nodiscard]] const SequenceCounters& counters() const noexcept { return counters_; }
    void reset() noexcept {
        counters_ = {};
        high_water_ = 0;
        observed_ = false;
    }

private:
    static void increment(std::uint64_t& value) noexcept {
        if (value != std::numeric_limits<std::uint64_t>::max()) {
            ++value;
        }
    }
    static void add(std::uint64_t& value, std::uint64_t addition) noexcept {
        const auto remaining = std::numeric_limits<std::uint64_t>::max() - value;
        value += addition > remaining ? remaining : addition;
    }

    SequenceCounters counters_{};
    std::uint64_t high_water_ = 0;
    bool observed_ = false;
};

} // namespace etf_genome
