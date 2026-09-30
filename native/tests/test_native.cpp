#include "etf_genome/csv.hpp"
#include "etf_genome/replay.hpp"
#include "etf_genome/spsc_queue.hpp"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

int checks = 0;

void check(bool condition, const std::string& message) {
    ++checks;
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void close(double actual, double expected, const std::string& message) {
    const auto tolerance = 1e-13 * std::max(1.0, std::abs(expected));
    check(std::abs(actual - expected) <= tolerance, message);
}

template <typename Function>
void rejects(Function&& function, const std::string& message) {
    bool rejected = false;
    try {
        function();
    } catch (const std::exception&) {
        rejected = true;
    }
    check(rejected, message);
}

void exposure_semantics() {
    const etf_genome::ExposureGraph graph({
        {"B", "sec:1", "AAA", 0.3},
        {"A", "sec:1", "AAA", 0.4},
        {"A", "sec:2", "BBB", -0.2},
        {"A", "sec:3", "CCC", std::nullopt},
        {"A", "sec:4", "DDD", 0.7},
        {"B", "sec:3", "CCC", std::nullopt},
        {"B", "sec:5", "EEE", std::nullopt},
        {"B", "sec:2", "BBB", 0.0},
    });
    check(graph.fund_ids() == std::vector<std::string>({"A", "B"}), "ETF ids are sorted");
    const auto resolved = graph.resolve({{"aaa", -0.1}, {"sec:2", -0.5}, {"CCC", 0.0}});
    check(resolved.values.size() == 3, "Canonical ids and ticker keys resolve");
    auto workspace = graph.make_workspace();
    graph.evaluate(resolved.values, workspace);
    const auto& a = workspace.impacts()[0];
    const auto& b = workspace.impacts()[1];
    close(a.direct_shock, 0.06, "Short holding reverses negative shock");
    close(a.covered_weight, 0.2, "Covered weight is signed");
    close(a.weight_sum, 0.9, "Weight sum is not normalized");
    check(a.missing_weight_count == 1, "Missing shocked weight is counted, including zero shock");
    close(b.direct_shock, -0.03, "Other fund direct exposure");
    close(b.covered_weight, 0.3, "Zero holding does not change covered mass");
    check(b.missing_weight_count == 1, "Unshocked missing weight is not counted");
    graph.evaluate({}, workspace);
    close(workspace.impacts()[0].direct_shock, 0.0, "Workspace resets between scenarios");
    close(workspace.impacts()[0].covered_weight, 0.0, "Reset clears previous covered weight");
    close(workspace.impacts()[0].weight_sum, 0.9, "Reset preserves graph weight sum");
    check(workspace.impacts()[0].missing_weight_count == 0, "Reset clears missing count");
    const auto index = graph.resolve({{"sec:2", -0.5}}).values.front().security_index;
    graph.evaluate_one(index, -0.5, workspace);
    close(workspace.impacts()[0].direct_shock, 0.1, "Sparse single event matches scenario exposure");
    close(workspace.impacts()[0].covered_weight, -0.2, "Sparse negative covered weight is retained");
}

void resolution_and_duplicates() {
    const etf_genome::ExposureGraph graph({
        {"A", "id:1", "DUP", 0.2},
        {"A", "id:2", "dup", 0.3},
        {"A", "id:1", "DUP", 0.1},
        {"A", "CANON", "OTHER", 0.4},
        {"A", "id:3", "CANON", 0.5},
    });
    const auto resolved = graph.resolve({{"dup", -0.2}, {"id:1", -0.1}, {"CANON", -0.3},
                                          {"missing", 0.1}, {"OTHER", -0.4}});
    check(resolved.ambiguous_keys == std::vector<std::string>({"DUP"}), "Ambiguous ticker excluded");
    check(resolved.unknown_keys == std::vector<std::string>({"missing"}), "Unknown security excluded");
    check(resolved.values.size() == 2, "Canonical id has precedence over ticker match");
    auto workspace = graph.make_workspace();
    graph.evaluate(resolved.values, workspace);
    close(workspace.impacts()[0].direct_shock, -0.19,
          "Duplicate holdings sum and later alias overwrites earlier canonical value");
    close(workspace.impacts()[0].covered_weight, 0.7, "Duplicate weights count separately");
    close(workspace.impacts()[0].weight_sum, 1.5, "All holdings remain in reported weight sum");
}

void empty_and_invalid_inputs() {
    const etf_genome::ExposureGraph empty({});
    auto empty_workspace = empty.make_workspace();
    empty.evaluate({}, empty_workspace);
    check(empty_workspace.impacts().empty(), "Empty graph returns no funds");
    check(empty.resolve({{"unknown", 0.1}}).values.empty(), "Empty graph resolves no securities");
    rejects([&] { empty.evaluate_one(0, 0.1, empty_workspace); }, "Empty graph cannot evaluate index");
    rejects([&] { etf_genome::replay_spsc(empty, 1); }, "Replay rejects empty graph");
    const auto infinity = std::numeric_limits<double>::infinity();
    const auto nan = std::numeric_limits<double>::quiet_NaN();
    rejects([&] { etf_genome::ExposureGraph graph({{"A", "1", "", infinity}}); },
            "Infinite weights rejected");
    rejects([&] { etf_genome::ExposureGraph graph({{"A", "1", "", nan}}); }, "NaN weights rejected");
    rejects([] { etf_genome::ExposureGraph graph({{"", "1", "", 0.1}}); }, "Empty fund id rejected");
    const etf_genome::ExposureGraph graph({{"A", "1", "", 0.5}, {"A", "2", "", 0.2}});
    auto workspace = graph.make_workspace();
    rejects([&] { graph.resolve({{"1", infinity}}); }, "Infinite shocks rejected");
    rejects([&] { graph.resolve({{"unknown", nan}}); }, "Nonfinite unknown shocks also rejected");
    rejects([&] { graph.evaluate({{0, 0.1}, {0, 0.2}}, workspace); }, "Duplicate indexed shocks rejected");
    rejects([&] { graph.evaluate({{1, 0.1}, {0, 0.2}}, workspace); }, "Descending indexed shocks rejected");
    rejects([&] { graph.evaluate({{2, 0.1}}, workspace); }, "Out-of-range indexed shock rejected");
    rejects([&] { graph.evaluate_one(0, nan, workspace); }, "NaN event rejected");
    rejects([&] { graph.evaluate({}, empty_workspace); }, "Wrong workspace dimensions rejected");
    const auto maximum = std::numeric_limits<double>::max();
    rejects([&] {
        etf_genome::ExposureGraph overflowing({{"A", "1", "", maximum}, {"A", "2", "", maximum}});
    }, "Overflowing weight sum rejected");
    const etf_genome::ExposureGraph large({{"A", "1", "", maximum}});
    auto large_workspace = large.make_workspace();
    rejects([&] { large.evaluate_one(0, 2.0, large_workspace); }, "Overflowing exposure rejected");
    rejects([] { etf_genome::make_synthetic_graph(1, 0, 1); }, "Synthetic dimensions validated");
}

void scalar_reference() {
    std::vector<etf_genome::Holding> holdings;
    std::map<std::string, double> shocks;
    std::uint32_t state = 7;
    for (std::size_t security = 0; security < 48; security += 5) {
        shocks.emplace("SEC_" + std::to_string(security),
                       (static_cast<double>(security) - 20.0) / 100.0);
    }
    for (std::size_t fund = 0; fund < 32; ++fund) {
        for (std::size_t edge = 0; edge < 60; ++edge) {
            state = state * 1664525U + 1013904223U;
            const auto security = state % 48U;
            const auto weight = (static_cast<double>(state % 200U) - 100.0) / 1000.0;
            holdings.push_back({"ETF_" + std::to_string(fund), "SEC_" + std::to_string(security), "",
                                edge % 13 == 0 ? std::nullopt : std::optional<double>{weight}});
        }
    }
    std::vector<std::pair<std::string, double>> keyed(shocks.begin(), shocks.end());
    const etf_genome::ExposureGraph graph(holdings);
    auto workspace = graph.make_workspace();
    graph.evaluate(graph.resolve(keyed).values, workspace);
    for (std::size_t index = 0; index < graph.fund_ids().size(); ++index) {
        etf_genome::Impact expected;
        for (const auto& holding : holdings) {
            if (holding.etf_id != graph.fund_ids()[index]) {
                continue;
            }
            const auto shock = shocks.find(holding.security_id);
            if (!holding.weight) {
                if (shock != shocks.end()) {
                    ++expected.missing_weight_count;
                }
            } else {
                expected.weight_sum += *holding.weight;
                if (shock != shocks.end()) {
                    expected.covered_weight += *holding.weight;
                    expected.direct_shock += *holding.weight * shock->second;
                }
            }
        }
        const auto& actual = workspace.impacts()[index];
        close(actual.direct_shock, expected.direct_shock, "Sparse engine matches scalar direct exposure");
        close(actual.covered_weight, expected.covered_weight, "Sparse engine matches scalar coverage");
        close(actual.weight_sum, expected.weight_sum, "Sparse engine matches scalar weight sums");
        check(actual.missing_weight_count == expected.missing_weight_count,
              "Sparse engine matches scalar missing weight count");
    }
}

void csv_contract() {
    std::istringstream edges("\xEF\xBB\xBF" "\"etf_node_id\",security_node_id,security_ticker,portfolio_weight\r\n"
                             "\"ETF,\"\"A\"\"\",SEC_1,TICK,-0.25\r\n"
                             "B,SEC_2,,\r\n"
                             "\"ETF\nC\",SEC_3,C,0");
    const auto holdings = etf_genome::read_holdings_csv(edges);
    check(holdings.size() == 3 && holdings[0].etf_id == "ETF,\"A\"", "Quoted comma and quote parsed");
    close(*holdings[0].weight, -0.25, "CSV keeps negative weights");
    check(!holdings[1].weight.has_value(), "Blank CSV weight is missing");
    check(holdings[2].weight == std::optional<double>{0.0}, "CSV zero differs from missing weight");
    check(holdings[2].etf_id == "ETF\nC", "Quoted multiline field parsed");
    const etf_genome::ExposureGraph graph(holdings);
    std::istringstream shocks("key,shock\nSEC_1,-0.1\n");
    auto workspace = graph.make_workspace();
    graph.evaluate(graph.resolve(etf_genome::read_shocks_csv(shocks)).values, workspace);
    std::ostringstream output;
    etf_genome::write_impacts_csv(output, graph, workspace);
    check(output.str().find("\"ETF,\"\"A\"\"\"") != std::string::npos, "Output quotes ids safely");
    check(output.str().find("\"ETF\nC\"") != std::string::npos, "Output quotes multiline ids");
    for (const auto* malformed : {"wrong,header\n", "key,shock\nA,nan\n", "key,shock\nA,inf\n",
                                  "key,shock\nA,1e400\n", "key,shock\nA,0.2extra\n",
                                  "key,shock\nA, 0.2\n", "key,shock\nA,\n",
                                  "key,shock\nA,0.1\nA,0.2\n", "key,shock\n\"A,0.1\n",
                                  "key,shock\n\"A\"x,0.1\n", "key,shock\nA\"x,0.1\n",
                                  "key,shock\nA,0.1,extra\n"}) {
        rejects([&] {
            std::istringstream input(malformed);
            etf_genome::read_shocks_csv(input);
        }, "Malformed shock CSV rejected");
    }
    std::istringstream header_only("etf_node_id,security_node_id,security_ticker,portfolio_weight\n");
    check(etf_genome::read_holdings_csv(header_only).empty(), "Header-only graph CSV is valid");
    rejects([] {
        std::istringstream oversized("key,shock\n" + std::string(4097, 'A') + ",0.1\n");
        etf_genome::read_shocks_csv(oversized);
    }, "Oversized CSV field rejected before unbounded growth");
    rejects([] {
        std::istringstream invalid_bom("\xEF" "key,shock\n");
        etf_genome::read_shocks_csv(invalid_bom);
    }, "Malformed BOM rejected");
}

void queue_boundaries_and_wrap() {
    etf_genome::SpscQueue<std::uint64_t, 1> one;
    std::uint64_t value = 99;
    check(!one.try_pop(value) && value == 99, "Empty queue preserves output argument");
    for (std::uint64_t sequence = 0; sequence < 100; ++sequence) {
        check(one.try_push(sequence), "Single-slot queue accepts one item");
        check(!one.try_push(sequence + 1), "Single-slot queue reports full");
        check(one.try_pop(value) && value == sequence, "Single-slot queue wraps without loss");
    }
    etf_genome::SpscQueue<std::uint64_t, 3> three;
    check(three.capacity() == 3, "Capacity is usable item count");
    for (std::uint64_t pass = 0; pass < 100; ++pass) {
        for (std::uint64_t offset = 0; offset < 3; ++offset) {
            check(three.try_push(pass * 3 + offset), "Non-power-of-two queue fills");
        }
        check(!three.try_push(0), "Non-power-of-two queue reports full");
        for (std::uint64_t offset = 0; offset < 3; ++offset) {
            check(three.try_pop(value) && value == pass * 3 + offset,
                  "Non-power-of-two queue preserves FIFO across wrap");
        }
        check(!three.try_pop(value), "Non-power-of-two queue empties");
    }
}

void queue_concurrency() {
    struct Payload {
        std::uint64_t sequence;
        std::uint64_t inverse;
        double value;
    };
    etf_genome::SpscQueue<Payload, 31> queue;
    constexpr std::uint64_t count = 300000;
    std::thread producer([&] {
        for (std::uint64_t index = 0; index < count; ++index) {
            const Payload item{index, ~index, static_cast<double>(index) * 0.125};
            while (!queue.try_push(item)) {
                std::this_thread::yield();
            }
        }
    });
    bool valid = true;
    for (std::uint64_t expected = 0; expected < count; ++expected) {
        Payload item{};
        while (!queue.try_pop(item)) {
            std::this_thread::yield();
        }
        valid = valid && item.sequence == expected && item.inverse == ~expected &&
                item.value == static_cast<double>(expected) * 0.125;
    }
    producer.join();
    check(valid, "Concurrent queue publishes whole payloads once in FIFO order");
    Payload item{};
    check(!queue.try_pop(item), "Concurrent transfer drains queue");
}

void replay_consistency() {
    const auto graph = etf_genome::make_synthetic_graph(16, 64, 16);
    const auto sequential = etf_genome::replay_single_threaded(graph, 40000);
    const auto concurrent = etf_genome::replay_spsc(graph, 40000);
    check(sequential.events == 40000 && concurrent.events == 40000, "Replay consumes exact event count");
    check(sequential.checksum == concurrent.checksum, "Replay checksum matches sequential event order");
    check(sequential.elapsed_seconds >= 0.0 && concurrent.elapsed_seconds >= 0.0,
          "Replay uses nonnegative steady-clock duration");
    check(etf_genome::replay_spsc(graph, 0).events == 0, "Zero-event replay terminates");
    const auto maximum_event = etf_genome::synthetic_event(std::numeric_limits<std::uint64_t>::max(), 64);
    check(maximum_event.security_index < 64 && std::isfinite(maximum_event.shock),
          "Synthetic event generation handles maximum sequence without overflow");
}

} // namespace

int main() {
    try {
        exposure_semantics();
        resolution_and_duplicates();
        empty_and_invalid_inputs();
        scalar_reference();
        csv_contract();
        queue_boundaries_and_wrap();
        queue_concurrency();
        replay_consistency();
        std::cout << "Passed " << checks << " native checks\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Test failed: " << error.what() << '\n';
        return 1;
    }
}
