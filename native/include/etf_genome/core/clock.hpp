#pragma once

#include <chrono>
#include <cstdint>

#if defined(__linux__)
#include <time.h>
#endif

namespace etf_genome {

// Process-wide clock selection occurs on the first call, before benchmark warm-up.
// Linux uses CLOCK_MONOTONIC_RAW when the initial probe succeeds. The fallback is
// steady_clock. Once selected, the clock domain never changes during processing.
// Timestamps can be compared between processes only on the same host/clock domain.
[[nodiscard]] inline std::uint64_t monotonic_now_ns() noexcept {
#if defined(__linux__)
    static const bool raw_available = []() noexcept {
        timespec probe{};
        return ::clock_gettime(CLOCK_MONOTONIC_RAW, &probe) == 0;
    }();
    if (raw_available) {
        timespec value{};
        if (::clock_gettime(CLOCK_MONOTONIC_RAW, &value) == 0) {
            return static_cast<std::uint64_t>(value.tv_sec) * 1000000000ULL +
                   static_cast<std::uint64_t>(value.tv_nsec);
        }
        // Returning zero exposes an unusable timestamp to latency validation;
        // switching clocks here would silently produce incomparable samples.
        return 0;
    }
#endif
    const auto value = std::chrono::steady_clock::now().time_since_epoch();
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(value).count());
}

} // namespace etf_genome
