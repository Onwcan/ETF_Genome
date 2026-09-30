#pragma once

#include "etf_genome/exposure.hpp"

#include <cstddef>
#include <cstdint>

namespace etf_genome {

struct ShockEvent {
    std::uint64_t sequence;
    std::uint32_t security_index;
    double shock;
};

struct ReplayResult {
    std::uint64_t events = 0;
    std::uint64_t producer_retries = 0;
    std::uint64_t consumer_retries = 0;
    double checksum = 0.0;
    double elapsed_seconds = 0.0;
};

ShockEvent synthetic_event(std::uint64_t sequence, std::size_t security_count);
ReplayResult replay_single_threaded(const ExposureGraph& graph, std::uint64_t event_count);
ReplayResult replay_spsc(const ExposureGraph& graph, std::uint64_t event_count);

} // namespace etf_genome
