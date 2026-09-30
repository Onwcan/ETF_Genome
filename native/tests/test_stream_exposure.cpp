#include "etf_genome/risk/price_exposure.hpp"
#include "etf_genome/risk/snapshot.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace {
void check(bool valid, const char* why) {
    if (!valid) { throw std::runtime_error(why); }
}
void near(double actual, double expected) {
    check(std::abs(actual - expected) <= 1e-11 * std::max(1.0, std::abs(expected)), "Exposure mismatch");
}
etf_genome::MarketMessage price(std::uint32_t security, std::int64_t ticks) {
    etf_genome::MarketMessage message{};
    message.type = etf_genome::MessageType::PriceUpdate;
    message.instrument_id = security;
    message.price_ticks = ticks;
    return message;
}
template<class F> void rejects(F&& action) {
    bool failed = false;
    try { action(); } catch (const std::exception&) { failed = true; }
    check(failed, "Malformed snapshot accepted");
}
std::string saved(const etf_genome::ExposureGraph& graph) {
    std::ostringstream output(std::ios::binary);
    etf_genome::write_binary_snapshot(output, graph);
    return output.str();
}
etf_genome::ExposureGraph loaded(const std::string& bytes) {
    std::istringstream input(bytes, std::ios::binary);
    return etf_genome::read_binary_snapshot(input);
}
std::uint64_t integer_at(const std::string& bytes, std::size_t offset, unsigned width) {
    std::uint64_t value = 0;
    for (unsigned index = 0; index < width; ++index) {
        value = (value << 8U) | static_cast<unsigned char>(bytes.at(offset + index));
    }
    return value;
}
void set_integer(std::string& bytes, std::size_t offset, unsigned width, std::uint64_t value) {
    for (unsigned index = 0; index < width; ++index) {
        bytes.at(offset + index) = std::bit_cast<char>(static_cast<unsigned char>(
            value >> ((width - index - 1U) * 8U)));
    }
}
void rehash(std::string& bytes) {
    std::uint64_t hash = 14695981039346656037ULL;
    for (std::size_t index = 64; index < bytes.size(); ++index) {
        hash ^= static_cast<unsigned char>(bytes[index]);
        hash *= 1099511628211ULL;
    }
    set_integer(bytes, 48, 8, hash);
}
void malformed_binary_checks(const std::string& bytes) {
    struct Mutation { std::size_t offset; unsigned width; std::uint64_t value; };
    for (const auto mutation : {
        Mutation{10, 2, 1}, Mutation{12, 4, 63}, Mutation{16, 4, 100001},
        Mutation{20, 4, 100001}, Mutation{24, 8, 1000001}, Mutation{32, 4, 1000001},
        Mutation{36, 4, 1}, Mutation{40, 8, 64U * 1024U * 1024U + 1U}, Mutation{56, 8, 1}}) {
        auto corrupt = bytes;
        set_integer(corrupt, mutation.offset, mutation.width, mutation.value);
        rejects([&] { loaded(corrupt); });
    }
    const auto funds = integer_at(bytes, 16, 4), securities = integer_at(bytes, 20, 4);
    const auto edges = integer_at(bytes, 24, 8), aliases = integer_at(bytes, 32, 4);
    std::size_t position = 64;
    for (std::uint64_t index = 0; index < funds + securities; ++index) {
        position += 4 + static_cast<std::size_t>(integer_at(bytes, position, 4));
    }
    const auto first_alias_index = position + 4 + static_cast<std::size_t>(integer_at(bytes, position, 4));
    for (std::uint64_t index = 0; index < aliases; ++index) {
        position += 8 + static_cast<std::size_t>(integer_at(bytes, position, 4));
    }
    const auto links = position + static_cast<std::size_t>(securities + 1) * 8;
    // Recomputed checksums ensure structural validation itself rejects these.
    for (const auto mutation : {
        Mutation{64, 4, 0}, Mutation{first_alias_index, 4, securities},
        Mutation{position + 8, 8, edges + 1}, Mutation{links, 4, funds},
        Mutation{links + 4, 1, 2}, Mutation{links + 5, 3, 1},
        Mutation{links + 8, 8, 0x7ff8000000000000ULL}, Mutation{links + 4, 1, 0}}) {
        auto corrupt = bytes;
        set_integer(corrupt, mutation.offset, mutation.width, mutation.value);
        rehash(corrupt);
        rejects([&] { loaded(corrupt); });
    }
}
void stream_checks() {
    const etf_genome::ExposureGraph graph({
        {"A", "sec:0", "ZERO", 0.4}, {"A", "sec:0", "ALIAS", 0.1},
        {"B", "sec:0", "ZERO", -0.3}, {"B", "sec:1", "ONE", 0.7},
        {"A", "sec:1", "ONE", std::nullopt}, {"A", "sec:2", "TWO", 0.0},
    });
    const auto offsets = graph.security_offsets();
    check(offsets.size() == 4 && offsets[0] == 0 && offsets[1] == 3 && offsets[3] == 6, "Sparse offsets");
    check(graph.security_exposures(99).empty(), "Out-of-range read must be empty");
    etf_genome::PriceExposureEngine engine(graph);
    check(engine.on_message(price(0, 10000)), "First price");
    check(engine.on_message(price(1, 20000)), "Second reference");
    for (std::uint32_t index = 0; index < 1000; ++index) {
        const auto first = static_cast<std::int64_t>(10000 + index);
        const auto second = static_cast<std::int64_t>(20000 - index);
        check(engine.on_message(price(0, first)) && engine.on_message(price(1, second)), "Incremental update");
        const double r0 = static_cast<double>(first) / 10000.0 - 1.0;
        const double r1 = static_cast<double>(second) / 20000.0 - 1.0;
        near(engine.fund_impacts()[0], 0.5 * r0);
        near(engine.fund_impacts()[1], -0.3 * r0 + 0.7 * r1);
        near(engine.checksum(), 0.2 * r0 + 0.7 * r1);
    }
    auto trade = price(0, 1);
    trade.type = etf_genome::MessageType::Trade;
    const auto before = engine.checksum();
    check(engine.on_message(trade), "Trade activity accepted");
    near(engine.checksum(), before);
    check(!engine.on_message(price(100, 1000)), "Invalid instrument rejected");
    check(engine.error() == etf_genome::PriceError::InvalidInstrument, "Error category");
    engine.reset();
    check(!engine.on_message(price(0, 0)), "Nonpositive price rejected");
    engine.reset();
    etf_genome::MarketMessage start{};
    start.type = etf_genome::MessageType::SnapshotStart;
    start.instrument_count = 2;
    check(!engine.on_message(start), "Snapshot count mismatch rejected");
    engine.reset();
    start.instrument_count = 3;
    check(engine.on_message(start), "Matching snapshot accepted");
    near(engine.checksum(), 0);
    const auto bytes = saved(graph);
    malformed_binary_checks(bytes);
    const auto roundtrip = loaded(bytes);
    check(saved(roundtrip) == bytes, "Deterministic binary round trip");
    check(roundtrip.fund_ids() == graph.fund_ids() && roundtrip.security_ids() == graph.security_ids(), "Snapshot ids");
    const auto shocks = graph.resolve({{"ALIAS", -0.1}, {"ONE", 0.2}});
    const auto second_shocks = roundtrip.resolve({{"ALIAS", -0.1}, {"ONE", 0.2}});
    auto first_ws = graph.make_workspace(), second_ws = roundtrip.make_workspace();
    graph.evaluate(shocks.values, first_ws);
    roundtrip.evaluate(second_shocks.values, second_ws);
    for (std::size_t index = 0; index < first_ws.impacts().size(); ++index) {
        near(first_ws.impacts()[index].direct_shock, second_ws.impacts()[index].direct_shock);
        check(first_ws.impacts()[index].missing_weight_count == second_ws.impacts()[index].missing_weight_count, "Missing preserved");
    }
    auto corrupt = bytes;
    corrupt[0] = 'X'; rejects([&] { loaded(corrupt); });
    corrupt = bytes; corrupt[9] = 2; rejects([&] { loaded(corrupt); });
    corrupt = bytes; corrupt.back() ^= 1; rejects([&] { loaded(corrupt); });
    rejects([&] { loaded(bytes.substr(0, 40)); });
    rejects([&] { loaded(bytes.substr(0, bytes.size() - 1)); });
    rejects([&] { loaded(bytes + "extra"); });
    auto invalid = graph.snapshot_data();
    invalid.offsets[1] = 100000;
    rejects([&] { (void)etf_genome::ExposureGraph::from_snapshot(invalid); });
    invalid = graph.snapshot_data(); invalid.links[0].fund_index = 100000;
    rejects([&] { (void)etf_genome::ExposureGraph::from_snapshot(invalid); });
    invalid = graph.snapshot_data(); invalid.links[0].weight = std::numeric_limits<double>::quiet_NaN();
    rejects([&] { (void)etf_genome::ExposureGraph::from_snapshot(invalid); });
    const etf_genome::ExposureGraph cancellation({{"A","a","AA",1e308}, {"A","b","BB",-1e308}, {"A","a","AA",1e308}});
    check(saved(loaded(saved(cancellation))) == saved(cancellation), "Extreme cancellation round trip");
    check(loaded(saved(etf_genome::ExposureGraph({}))).edge_count() == 0, "Empty graph round trip");
    const etf_genome::ExposureGraph huge({{"A", "SEC", "BIG", 1e308}});
    etf_genome::PriceExposureEngine overflowing(huge);
    check(overflowing.on_message(price(0, 1)), "Overflow test reference accepted");
    check(!overflowing.on_message(price(0, 3)) &&
          overflowing.error() == etf_genome::PriceError::Overflow, "Price overflow rejected");
    check(!overflowing.on_message(price(0, 1)), "Overflow state stays fatal");
}
}

int main() {
    try { stream_checks(); std::cout << "Stream exposure and snapshot tests passed\n"; return 0; }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
