#include "allocation_counter.hpp"

#include <exception>
#include <iostream>

int main() {
    try {
        const auto result = etf_genome::benchmark::allocation_counter_self_check();
        if (!result.passed()) {
            std::cerr << "Allocation hook counted " << result.observed_calls << " calls; expected "
                      << result.expected_calls << '\n';
            return 1;
        }
        std::cout << "Allocation counter self-check passed: " << result.observed_calls
                  << " known calls; untracked and nested/thread scopes verified\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Allocation counter self-check failed: " << error.what() << '\n';
        return 1;
    }
}
