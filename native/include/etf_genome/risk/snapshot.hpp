#pragma once

#include "etf_genome/exposure.hpp"

#include <iosfwd>

namespace etf_genome {

// Versioned big-endian sparse snapshot, retaining signed/missing weights and aliases.
// Integrity checksum detects accidental corruption; it does not authenticate input.
void write_binary_snapshot(std::ostream& output, const ExposureGraph& graph);
[[nodiscard]] ExposureGraph read_binary_snapshot(std::istream& input);

} // namespace etf_genome
