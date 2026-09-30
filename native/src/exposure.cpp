#include "etf_genome/exposure.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <stdexcept>
#include <tuple>

namespace etf_genome {
namespace {

std::string ascii_upper(std::string text) {
    for (auto& character : text) {
        if (character >= 'a' && character <= 'z') {
            character = static_cast<char>(character - 'a' + 'A');
        }
    }
    return text;
}

void finite(double value, const char* field) {
    if (!std::isfinite(value)) {
        throw std::invalid_argument(std::string(field) + " must be finite");
    }
}

} // namespace

ExposureGraph::ExposureGraph(std::vector<Holding> holdings) {
    for (const auto& holding : holdings) {
        if (holding.etf_id.empty() || holding.security_id.empty()) {
            throw std::invalid_argument("ETF and security ids must be nonempty");
        }
        if (holding.weight) {
            finite(*holding.weight, "portfolio weight");
        }
        fund_ids_.push_back(holding.etf_id);
        security_ids_.push_back(holding.security_id);
    }
    auto canonicalize = [](auto& ids) {
        std::sort(ids.begin(), ids.end());
        ids.erase(std::unique(ids.begin(), ids.end()), ids.end());
    };
    canonicalize(fund_ids_);
    canonicalize(security_ids_);
    std::unordered_map<std::string, std::size_t> fund_index;
    for (std::size_t index = 0; index < fund_ids_.size(); ++index) {
        fund_index.emplace(fund_ids_[index], index);
    }
    for (std::size_t index = 0; index < security_ids_.size(); ++index) {
        security_index_.emplace(security_ids_[index], index);
    }
    offsets_.assign(security_ids_.size() + 1, 0);
    weight_sums_.assign(fund_ids_.size(), 0.0);
    for (const auto& holding : holdings) {
        const auto security = security_index_.at(holding.security_id);
        ++offsets_[security + 1];
        if (!holding.ticker.empty()) {
            ticker_indices_[ascii_upper(holding.ticker)].push_back(security);
        }
    }
    for (auto& item : ticker_indices_) {
        canonicalize(item.second);
    }
    for (std::size_t index = 1; index < offsets_.size(); ++index) {
        offsets_[index] += offsets_[index - 1];
    }
    entries_.resize(holdings.size());
    auto cursor = offsets_;
    for (const auto& holding : holdings) {
        const auto security = security_index_.at(holding.security_id);
        entries_[cursor[security]++] = ExposureLink{fund_index.at(holding.etf_id),
                                           holding.weight.value_or(0.0), holding.weight.has_value()};
    }
    recompute_weight_sums();
}

void ExposureGraph::recompute_weight_sums() {
    // Canonical sparse order is shared by CSV construction and binary loading.
    // Scaling avoids an overflowing intermediate sum that later cancels.
    std::vector<double> scale(fund_ids_.size(), 0.0), totals(fund_ids_.size(), 0.0);
    std::vector<double> compensation(fund_ids_.size(), 0.0);
    for (const auto& link : entries_) {
        if (link.has_weight) { scale[link.fund_index] = std::max(scale[link.fund_index], std::abs(link.weight)); }
    }
    for (const auto& link : entries_) {
        if (!link.has_weight || scale[link.fund_index] == 0) { continue; }
        const auto fund = link.fund_index;
        const auto value = link.weight / scale[fund] - compensation[fund];
        const auto updated = totals[fund] + value;
        compensation[fund] = (updated - totals[fund]) - value;
        totals[fund] = updated;
    }
    weight_sums_.resize(fund_ids_.size());
    for (std::size_t fund = 0; fund < fund_ids_.size(); ++fund) {
        weight_sums_[fund] = totals[fund] * scale[fund];
        if (!std::isfinite(weight_sums_[fund])) {
            throw std::overflow_error("Portfolio weight sum exceeds finite double range");
        }
    }
}

std::span<const ExposureLink> ExposureGraph::security_exposures(std::size_t index) const noexcept {
    if (index >= security_ids_.size()) {
        return {};
    }
    return std::span<const ExposureLink>(entries_).subspan(offsets_[index],
                                                          offsets_[index + 1] - offsets_[index]);
}

GraphSnapshotData ExposureGraph::snapshot_data() const {
    GraphSnapshotData data{fund_ids_, security_ids_, {}, offsets_, entries_};
    for (const auto& [ticker, indices] : ticker_indices_) {
        for (const auto index : indices) {
            data.aliases.push_back({ticker, index});
        }
    }
    std::sort(data.aliases.begin(), data.aliases.end(), [](const auto& left, const auto& right) {
        return std::tie(left.ticker, left.security_index) < std::tie(right.ticker, right.security_index);
    });
    return data;
}

ExposureGraph ExposureGraph::from_snapshot(GraphSnapshotData data) {
    auto valid_ids = [](const auto& ids) {
        return std::all_of(ids.begin(), ids.end(), [](const auto& id) { return !id.empty(); }) &&
               std::is_sorted(ids.begin(), ids.end()) &&
               std::adjacent_find(ids.begin(), ids.end()) == ids.end();
    };
    if (!valid_ids(data.fund_ids) || !valid_ids(data.security_ids) ||
        data.offsets.size() != data.security_ids.size() + 1 || data.offsets.front() != 0 ||
        data.offsets.back() != data.links.size() || !std::is_sorted(data.offsets.begin(), data.offsets.end())) {
        throw std::invalid_argument("Invalid graph snapshot ids or sparse offsets");
    }
    ExposureGraph graph({});
    graph.fund_ids_ = std::move(data.fund_ids);
    graph.security_ids_ = std::move(data.security_ids);
    graph.offsets_ = std::move(data.offsets);
    graph.entries_ = std::move(data.links);
    graph.weight_sums_.assign(graph.fund_ids_.size(), 0.0);
    for (std::size_t index = 0; index < graph.security_ids_.size(); ++index) {
        graph.security_index_.emplace(graph.security_ids_[index], index);
    }
    for (const auto& link : graph.entries_) {
        if (link.fund_index >= graph.fund_ids_.size() || !std::isfinite(link.weight) ||
            (!link.has_weight && link.weight != 0.0)) {
            throw std::invalid_argument("Invalid graph snapshot exposure link");
        }
    }
    for (auto& alias : data.aliases) {
        if (alias.ticker.empty() || alias.security_index >= graph.security_ids_.size()) {
            throw std::invalid_argument("Invalid graph snapshot ticker alias");
        }
        graph.ticker_indices_[ascii_upper(std::move(alias.ticker))].push_back(alias.security_index);
    }
    for (auto& [ticker, indices] : graph.ticker_indices_) {
        (void)ticker;
        std::sort(indices.begin(), indices.end());
        indices.erase(std::unique(indices.begin(), indices.end()), indices.end());
    }
    graph.recompute_weight_sums();
    return graph;
}

ResolvedShocks ExposureGraph::resolve(
    const std::vector<std::pair<std::string, double>>& shocks) const {
    ResolvedShocks result;
    std::map<std::size_t, double> values;
    for (const auto& item : shocks) {
        finite(item.second, "shock");
        const auto direct = security_index_.find(item.first);
        if (direct != security_index_.end()) {
            values[direct->second] = item.second;
            continue;
        }
        const auto upper = ascii_upper(item.first);
        const auto ticker = ticker_indices_.find(upper);
        if (ticker == ticker_indices_.end()) {
            result.unknown_keys.push_back(item.first);
        } else if (ticker->second.size() != 1) {
            result.ambiguous_keys.push_back(upper);
        } else {
            values[ticker->second.front()] = item.second;
        }
    }
    result.values.reserve(values.size());
    for (const auto& value : values) {
        result.values.push_back(IndexedShock{value.first, value.second});
    }
    return result;
}

void ExposureGraph::reset(ExposureWorkspace& workspace) const {
    if (workspace.impacts_.size() != fund_ids_.size()) {
        throw std::invalid_argument("Workspace fund count does not match graph");
    }
    for (std::size_t index = 0; index < fund_ids_.size(); ++index) {
        workspace.impacts_[index] = Impact{0.0, 0.0, weight_sums_[index], 0};
    }
}

void ExposureGraph::accumulate(std::size_t security_index, double shock,
                               ExposureWorkspace& workspace) const {
    for (auto index = offsets_[security_index]; index < offsets_[security_index + 1]; ++index) {
        const auto& entry = entries_[index];
        auto& impact = workspace.impacts_[entry.fund_index];
        if (!entry.has_weight) {
            ++impact.missing_weight_count;
        } else {
            impact.covered_weight += entry.weight;
            impact.direct_shock += entry.weight * shock;
        }
    }
}

void ExposureGraph::validate_results(const ExposureWorkspace& workspace) {
    for (const auto& impact : workspace.impacts_) {
        if (!std::isfinite(impact.direct_shock) || !std::isfinite(impact.covered_weight)) {
            throw std::overflow_error("Exposure exceeds finite double range");
        }
    }
}

void ExposureGraph::evaluate(const std::vector<IndexedShock>& shocks,
                             ExposureWorkspace& workspace) const {
    // Validate before touching the workspace, including duplicate shocks that would double count.
    std::size_t previous = 0;
    bool first = true;
    for (const auto& shock : shocks) {
        if (shock.security_index >= security_ids_.size() ||
            (!first && shock.security_index <= previous)) {
            throw std::invalid_argument("Shock indices must be in range, unique, and increasing");
        }
        finite(shock.shock, "shock");
        previous = shock.security_index;
        first = false;
    }
    reset(workspace);
    for (const auto& shock : shocks) {
        accumulate(shock.security_index, shock.shock, workspace);
    }
    validate_results(workspace);
}

void ExposureGraph::evaluate_one(std::size_t security_index, double shock,
                                 ExposureWorkspace& workspace) const {
    if (security_index >= security_ids_.size()) {
        throw std::invalid_argument("Security index is outside graph");
    }
    finite(shock, "shock");
    reset(workspace);
    accumulate(security_index, shock, workspace);
    validate_results(workspace);
}

ExposureGraph make_synthetic_graph(std::size_t funds, std::size_t securities,
                                   std::size_t holdings_per_fund) {
    if (funds == 0 || securities == 0 || holdings_per_fund == 0 ||
        holdings_per_fund > securities || funds > 100000 || securities > 100000 ||
        holdings_per_fund > 10000000 / funds) {
        throw std::invalid_argument("Invalid synthetic graph dimensions");
    }
    std::vector<Holding> holdings;
    holdings.reserve(funds * holdings_per_fund);
    for (std::size_t fund = 0; fund < funds; ++fund) {
        for (std::size_t offset = 0; offset < holdings_per_fund; ++offset) {
            const auto security = (fund * 13 + offset) % securities;
            const auto weight = offset % 11 == 0 ? -0.25 / static_cast<double>(holdings_per_fund)
                                                : 1.0 / static_cast<double>(holdings_per_fund);
            holdings.push_back(Holding{"synthetic:ETF_" + std::to_string(fund),
                                       "synthetic:SEC_" + std::to_string(security),
                                       "SYN" + std::to_string(security),
                                       offset % 29 == 0 ? std::nullopt : std::optional<double>{weight}});
        }
    }
    return ExposureGraph(std::move(holdings));
}

} // namespace etf_genome
