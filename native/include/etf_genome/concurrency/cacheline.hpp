#pragma once

#include <cstddef>
#include <new>

namespace etf_genome {

// Opt-in: the standard value can change with compiler target options and hence ABI.
// Stable 64-byte padding remains the portable default; no speedup is presumed.
#if defined(ETF_GENOME_USE_HARDWARE_INTERFERENCE_SIZE) && defined(__cpp_lib_hardware_interference_size)
inline constexpr std::size_t cacheline_bytes = std::hardware_destructive_interference_size;
#else
inline constexpr std::size_t cacheline_bytes = 64;
#endif

} // namespace etf_genome
