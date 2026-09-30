#pragma once

#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace etf_genome {

// Fixed 15 KiB storage: exact bins for 0..1023 ns, then 16 sub-bins per power of
// two through UINT64_MAX. Quantiles use nearest-rank and return a bin upper bound,
// capped by the observed maximum. Above 1023 ns, rounding error is <6.25% of the
// sample (plus integer rounding); min/max remain exact. Single-thread ownership.
class LatencyHistogram {
public:
    static constexpr std::size_t exact_bins = 1024;
    static constexpr std::size_t sub_bins = 16;
    static constexpr std::size_t bin_count = exact_bins + (64 - 10) * sub_bins;

    void record(std::uint64_t nanoseconds) noexcept {
        // Saturation is explicit rather than wrapping after UINT64_MAX samples.
        if (count_ == std::numeric_limits<std::uint64_t>::max()) {
            saturated_ = true;
            return;
        }
        ++bins_[index_for(nanoseconds)];
        if (count_ == 0 || nanoseconds < minimum_) {
            minimum_ = nanoseconds;
        }
        if (nanoseconds > maximum_) {
            maximum_ = nanoseconds;
        }
        ++count_;
    }

    [[nodiscard]] std::uint64_t count() const noexcept { return count_; }
    [[nodiscard]] std::uint64_t min() const noexcept { return minimum_; }
    [[nodiscard]] std::uint64_t max() const noexcept { return maximum_; }
    [[nodiscard]] bool saturated() const noexcept { return saturated_; }

    // Empty histogram or NaN percentile -> 0; <=0 -> min; >=100 -> exact max.
    [[nodiscard]] std::uint64_t percentile(double percent) const noexcept {
        if (count_ == 0 || std::isnan(percent)) {
            return 0;
        }
        if (percent <= 0.0) {
            return minimum_;
        }
        if (percent >= 100.0) {
            return maximum_;
        }
        const auto rank_value = std::ceil(static_cast<long double>(count_) *
                                         (static_cast<long double>(percent) / 100.0L));
        if (rank_value >= static_cast<long double>(count_)) {
            return maximum_;
        }
        const auto rank = rank_value < 1.0L ? std::uint64_t{1} :
                                            static_cast<std::uint64_t>(rank_value);
        std::uint64_t cumulative = 0;
        for (std::size_t index = 0; index < bin_count; ++index) {
            cumulative += bins_[index];
            if (cumulative >= rank) {
                const auto upper = upper_bound(index);
                return upper < maximum_ ? upper : maximum_;
            }
        }
        return maximum_;
    }

    void reset() noexcept {
        bins_.fill(0);
        count_ = 0;
        minimum_ = 0;
        maximum_ = 0;
        saturated_ = false;
    }

private:
    [[nodiscard]] static std::size_t index_for(std::uint64_t value) noexcept {
        if (value < exact_bins) {
            return static_cast<std::size_t>(value);
        }
        const auto exponent = static_cast<unsigned>(std::bit_width(value) - 1);
        const auto base = std::uint64_t{1} << exponent;
        const auto sub = (value - base) >> (exponent - 4);
        return exact_bins + static_cast<std::size_t>(exponent - 10) * sub_bins +
               static_cast<std::size_t>(sub);
    }

    [[nodiscard]] static std::uint64_t upper_bound(std::size_t index) noexcept {
        if (index < exact_bins) {
            return static_cast<std::uint64_t>(index);
        }
        const auto relative = index - exact_bins;
        const auto exponent = static_cast<unsigned>(relative / sub_bins + 10);
        const auto width = std::uint64_t{1} << (exponent - 4);
        const auto sub = static_cast<std::uint64_t>(relative % sub_bins);
        // This order also works for the last bin: no intermediate 2^64 value.
        return (std::uint64_t{1} << exponent) + sub * width + (width - 1);
    }

    std::array<std::uint64_t, bin_count> bins_{};
    std::uint64_t count_ = 0;
    std::uint64_t minimum_ = 0;
    std::uint64_t maximum_ = 0;
    bool saturated_ = false;
};

} // namespace etf_genome
