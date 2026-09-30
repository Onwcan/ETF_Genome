#pragma once

#include "etf_genome/exposure.hpp"

#include <istream>
#include <ostream>

namespace etf_genome {

// Strict headers; quoted fields, UTF-8 BOM and CRLF are accepted. Numbers must be finite.
// Limits per input: 64 MiB, 1M data rows, 4096 bytes/field, 16384 bytes/logical record.
std::vector<Holding> read_holdings_csv(std::istream& input);
std::vector<std::pair<std::string, double>> read_shocks_csv(std::istream& input);
void write_impacts_csv(std::ostream& output, const ExposureGraph& graph,
                       const ExposureWorkspace& workspace);

} // namespace etf_genome
