#pragma once

#include <cstdint>

namespace etf_genome::benchmark {
void reset_allocations() noexcept;
[[nodiscard]] std::uint64_t allocations() noexcept;
struct AllocationSelfCheck {
    std::uint64_t observed_calls = 0;
    std::uint64_t expected_calls = 11;
    [[nodiscard]] bool passed() const noexcept { return observed_calls == expected_calls; }
};
// Run before measurement with no concurrent instrumented work. Exercises direct
// scalar/array/aligned/nothrow calls, scope nesting and independent thread state.
[[nodiscard]] AllocationSelfCheck allocation_counter_self_check();
class AllocationScope {
public:
    explicit AllocationScope(bool enabled) noexcept;
    ~AllocationScope();
    AllocationScope(const AllocationScope&) = delete;
    AllocationScope& operator=(const AllocationScope&) = delete;
private:
    bool previous_;
};
} // namespace etf_genome::benchmark
