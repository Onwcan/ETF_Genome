#include "etf_genome/risk/price_exposure.hpp"

#include <algorithm>
#include <cmath>

namespace etf_genome {

PriceExposureEngine::PriceExposureEngine(const ExposureGraph& graph)
    : graph_(graph), reference_prices_(graph.security_ids().size(), 0),
      security_returns_(graph.security_ids().size(), 0.0), fund_impacts_(graph.fund_ids().size(), 0.0) {}

void PriceExposureEngine::reset() noexcept {
    std::fill(reference_prices_.begin(), reference_prices_.end(), 0);
    std::fill(security_returns_.begin(), security_returns_.end(), 0.0);
    std::fill(fund_impacts_.begin(), fund_impacts_.end(), 0.0);
    checksum_ = 0;
    updates_ = 0;
    error_ = PriceError::None;
}

bool PriceExposureEngine::on_message(const MarketMessage& message) noexcept {
    if (error_ != PriceError::None) {
        return false;
    }
    if (message.type == MessageType::SnapshotStart) {
        if (message.instrument_count != reference_prices_.size()) {
            error_ = PriceError::SnapshotMismatch;
            return false;
        }
        reset();
        return true;
    }
    if (message.type != MessageType::PriceUpdate) {
        return true;
    }
    const auto security = static_cast<std::size_t>(message.instrument_id);
    if (security >= reference_prices_.size()) {
        error_ = PriceError::InvalidInstrument;
        return false;
    }
    if (message.price_ticks <= 0) {
        error_ = PriceError::InvalidPrice;
        return false;
    }
    auto& reference = reference_prices_[security];
    ++updates_;
    if (reference == 0) {
        reference = message.price_ticks;
        return true;
    }
    const double current_return = static_cast<double>(message.price_ticks) /
                                      static_cast<double>(reference) - 1.0;
    const double change = current_return - security_returns_[security];
    // Only affected holdings are touched; there is no pass over all funds here.
    for (const auto& link : graph_.security_exposures(security)) {
        if (!link.has_weight) {
            continue;
        }
        const double contribution = link.weight * change;
        auto& impact = fund_impacts_[link.fund_index];
        impact += contribution;
        checksum_ += contribution;
        if (!std::isfinite(impact) || !std::isfinite(checksum_)) {
            error_ = PriceError::Overflow;
            return false; // Fatal state: discard partial results after an error.
        }
    }
    security_returns_[security] = current_return;
    return true;
}

} // namespace etf_genome
