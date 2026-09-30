#pragma once

#include "etf_genome/exposure.hpp"
#include "etf_genome/market/message.hpp"

#include <cstdint>
#include <span>
#include <vector>

namespace etf_genome {

enum class PriceError { None, InvalidInstrument, InvalidPrice, SnapshotMismatch, Overflow };

// One consumer owns this state. The immutable graph must outlive the engine.
class PriceExposureEngine {
public:
    explicit PriceExposureEngine(const ExposureGraph& graph);
    [[nodiscard]] bool on_message(const MarketMessage& message) noexcept;
    [[nodiscard]] std::span<const double> fund_impacts() const noexcept { return fund_impacts_; }
    [[nodiscard]] double checksum() const noexcept { return checksum_; }
    [[nodiscard]] std::uint64_t processed_updates() const noexcept { return updates_; }
    [[nodiscard]] PriceError error() const noexcept { return error_; }
    void reset() noexcept;

private:
    const ExposureGraph& graph_;
    std::vector<std::int64_t> reference_prices_;
    std::vector<double> security_returns_;
    std::vector<double> fund_impacts_;
    double checksum_ = 0;
    std::uint64_t updates_ = 0;
    PriceError error_ = PriceError::None;
};

} // namespace etf_genome
