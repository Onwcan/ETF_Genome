#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace etf_genome {

struct Holding {
    std::string etf_id;
    std::string security_id;
    std::string ticker;
    std::optional<double> weight;
};

struct Impact {
    double direct_shock = 0.0;
    double covered_weight = 0.0;
    double weight_sum = 0.0;
    std::size_t missing_weight_count = 0;
};

struct IndexedShock {
    std::size_t security_index;
    double shock;
};

struct ExposureLink {
    std::size_t fund_index;
    double weight;
    bool has_weight;
};

struct TickerAlias {
    std::string ticker;
    std::size_t security_index;
};

// A portable ownership boundary for snapshots and future bindings, with no OS state.
struct GraphSnapshotData {
    std::vector<std::string> fund_ids;
    std::vector<std::string> security_ids;
    std::vector<TickerAlias> aliases;
    std::vector<std::size_t> offsets;
    std::vector<ExposureLink> links;
};

struct ResolvedShocks {
    // Unique indices, sorted by canonical security id. Later aliases overwrite earlier aliases.
    std::vector<IndexedShock> values;
    std::vector<std::string> ambiguous_keys;
    std::vector<std::string> unknown_keys;
};

class ExposureGraph;

class ExposureWorkspace {
public:
    const std::vector<Impact>& impacts() const noexcept { return impacts_; }

private:
    friend class ExposureGraph;
    explicit ExposureWorkspace(std::size_t count) : impacts_(count) {}
    std::vector<Impact> impacts_;
};

class ExposureGraph {
public:
    explicit ExposureGraph(std::vector<Holding> holdings);

    const std::vector<std::string>& fund_ids() const noexcept { return fund_ids_; }
    const std::vector<std::string>& security_ids() const noexcept { return security_ids_; }
    std::size_t edge_count() const noexcept { return entries_.size(); }
    [[nodiscard]] std::span<const ExposureLink> security_exposures(std::size_t index) const noexcept;
    [[nodiscard]] std::span<const std::size_t> security_offsets() const noexcept { return offsets_; }
    [[nodiscard]] GraphSnapshotData snapshot_data() const;
    [[nodiscard]] static ExposureGraph from_snapshot(GraphSnapshotData data);

    ResolvedShocks resolve(const std::vector<std::pair<std::string, double>>& shocks) const;
    ExposureWorkspace make_workspace() const { return ExposureWorkspace(fund_ids_.size()); }

    // No allocation on the successful evaluation path. Workspace belongs to one caller/thread.
    // Pass resolve(...).values: indices must be unique, increasing, and within this graph.
    void evaluate(const std::vector<IndexedShock>& shocks, ExposureWorkspace& workspace) const;
    void evaluate_one(std::size_t security_index, double shock, ExposureWorkspace& workspace) const;

private:
    void reset(ExposureWorkspace& workspace) const;
    void accumulate(std::size_t security_index, double shock, ExposureWorkspace& workspace) const;
    static void validate_results(const ExposureWorkspace& workspace);
    void recompute_weight_sums();

    std::vector<std::string> fund_ids_;
    std::vector<std::string> security_ids_;
    std::unordered_map<std::string, std::size_t> security_index_;
    std::unordered_map<std::string, std::vector<std::size_t>> ticker_indices_;
    std::vector<std::size_t> offsets_;
    std::vector<ExposureLink> entries_;
    std::vector<double> weight_sums_;
};

ExposureGraph make_synthetic_graph(std::size_t funds = 128, std::size_t securities = 1024,
                                 std::size_t holdings_per_fund = 64);

} // namespace etf_genome
