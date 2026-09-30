#include "etf_genome/csv.hpp"
#include "etf_genome/replay.hpp"
#include "etf_genome/risk/snapshot.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <locale>
#include <stdexcept>
#include <string>

namespace {

void usage(std::ostream& output) {
    output << "ETF Genome native research tools (synthetic replay; no exchange execution)\n"
           << "  etf-genome-native demo\n"
           << "  etf-genome-native shock --edges PATH --shocks PATH\n"
           << "  etf-genome-native shock --snapshot PATH --shocks PATH\n"
           << "  etf-genome-native snapshot-save --edges PATH --output PATH\n"
           << "  etf-genome-native snapshot-info PATH\n"
           << "  etf-genome-native replay [event_count]   (default 200000; max 100000000)\n";
}

std::uint64_t count(const std::string& text) {
    std::uint64_t value = 0;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size() || value > 100000000U) {
        throw std::invalid_argument("Event count must be an integer from 0 through 100000000");
    }
    return value;
}

void shock_command(int argc, char** argv) {
    std::string edges_path;
    std::string shocks_path;
    std::string snapshot_path;
    for (int argument = 2; argument < argc; argument += 2) {
        if (argument + 1 == argc) {
            throw std::invalid_argument("A file option requires a path");
        }
        const std::string option = argv[argument];
        if (option == "--edges" && edges_path.empty()) {
            edges_path = argv[argument + 1];
        } else if (option == "--shocks" && shocks_path.empty()) {
            shocks_path = argv[argument + 1];
        } else if (option == "--snapshot" && snapshot_path.empty()) {
            snapshot_path = argv[argument + 1];
        } else {
            throw std::invalid_argument("Unknown or duplicate file option");
        }
    }
    if (edges_path.empty() == snapshot_path.empty() || shocks_path.empty()) {
        throw std::invalid_argument("shock requires exactly one of --edges/--snapshot plus --shocks");
    }
    std::ifstream edges_file(snapshot_path.empty() ? edges_path : snapshot_path, std::ios::binary);
    std::ifstream shocks_file(shocks_path, std::ios::binary);
    if (!edges_file || !shocks_file) {
        throw std::runtime_error("Cannot open input CSV file");
    }
    const etf_genome::ExposureGraph graph = snapshot_path.empty()
        ? etf_genome::ExposureGraph(etf_genome::read_holdings_csv(edges_file))
        : etf_genome::read_binary_snapshot(edges_file);
    const auto shocks = graph.resolve(etf_genome::read_shocks_csv(shocks_file));
    for (const auto& key : shocks.ambiguous_keys) {
        std::cerr << "Excluded ambiguous ticker: " << key << '\n';
    }
    for (const auto& key : shocks.unknown_keys) {
        std::cerr << "Excluded unknown shock key: " << key << '\n';
    }
    auto workspace = graph.make_workspace();
    graph.evaluate(shocks.values, workspace);
    etf_genome::write_impacts_csv(std::cout, graph, workspace);
}

void snapshot_save(int argc, char** argv) {
    std::string edges_path, output_path;
    for (int argument = 2; argument < argc; argument += 2) {
        if (argument + 1 >= argc) { throw std::invalid_argument("A file option requires a path"); }
        const std::string option = argv[argument];
        if (option == "--edges" && edges_path.empty()) { edges_path = argv[argument + 1]; }
        else if (option == "--output" && output_path.empty()) { output_path = argv[argument + 1]; }
        else { throw std::invalid_argument("Unknown or duplicate snapshot option"); }
    }
    if (edges_path.empty() || output_path.empty() || edges_path == output_path) {
        throw std::invalid_argument("snapshot-save requires distinct --edges and --output paths");
    }
    const auto source_path = std::filesystem::weakly_canonical(edges_path);
    const auto destination_path = std::filesystem::weakly_canonical(output_path);
    if (source_path == destination_path ||
        (std::filesystem::exists(destination_path) &&
         std::filesystem::equivalent(source_path, destination_path))) {
        throw std::invalid_argument("Snapshot output must not replace the holdings CSV");
    }
    std::ifstream source(edges_path, std::ios::binary);
    if (!source) { throw std::runtime_error("Cannot open holdings CSV"); }
    const etf_genome::ExposureGraph graph(etf_genome::read_holdings_csv(source));
    std::ofstream output(output_path, std::ios::binary | std::ios::trunc);
    if (!output) { throw std::runtime_error("Cannot open snapshot output"); }
    etf_genome::write_binary_snapshot(output, graph);
    output.flush();
    if (!output) { throw std::runtime_error("Binary snapshot flush failed"); }
    std::cout << "Saved snapshot: funds=" << graph.fund_ids().size()
              << " securities=" << graph.security_ids().size() << " edges=" << graph.edge_count() << '\n';
}

void snapshot_info(const char* path) {
    std::ifstream source(path, std::ios::binary);
    if (!source) { throw std::runtime_error("Cannot open binary snapshot"); }
    const auto graph = etf_genome::read_binary_snapshot(source);
    std::cout << "{\"snapshot_version\":1,\"funds\":" << graph.fund_ids().size()
              << ",\"securities\":" << graph.security_ids().size()
              << ",\"edges\":" << graph.edge_count() << "}\n";
}

void demo_command() {
    const etf_genome::ExposureGraph graph({
        {"synthetic:ETF_A", "synthetic:SEC_1", "SYN1", 0.2},
        {"synthetic:ETF_A", "synthetic:SEC_2", "SYN2", -0.1},
        {"synthetic:ETF_A", "synthetic:SEC_3", "SYN3", 0.5},
        {"synthetic:ETF_A", "synthetic:SEC_4", "SYN4", std::nullopt},
        {"synthetic:ETF_B", "synthetic:SEC_1", "SYN1", 0.4},
        {"synthetic:ETF_B", "synthetic:SEC_2", "SYN2", 0.6},
    });
    const auto shocks = graph.resolve({{"syn1", -0.1}, {"SYN2", 0.0}, {"SYN4", -0.2}});
    auto workspace = graph.make_workspace();
    graph.evaluate(shocks.values, workspace);
    etf_genome::write_impacts_csv(std::cout, graph, workspace);
}

void print_replay(const char* name, const etf_genome::ReplayResult& result) {
    const auto rate = result.elapsed_seconds > 0.0
                          ? static_cast<double>(result.events) / result.elapsed_seconds
                          : 0.0;
    std::cout << name << " events=" << result.events << " elapsed_seconds=" << result.elapsed_seconds
              << " events_per_second=" << rate << " checksum=" << result.checksum
              << " producer_retries=" << result.producer_retries
              << " consumer_retries=" << result.consumer_retries << '\n';
}

void replay_command(std::uint64_t events) {
    const auto graph = etf_genome::make_synthetic_graph();
    const auto warmup = std::min<std::uint64_t>(events, 10000);
    etf_genome::replay_single_threaded(graph, warmup);
    etf_genome::replay_spsc(graph, warmup);
    const auto serial = etf_genome::replay_single_threaded(graph, events);
    const auto concurrent = etf_genome::replay_spsc(graph, events);
    if (serial.events != concurrent.events || serial.checksum != concurrent.checksum) {
        throw std::runtime_error("Sequential and SPSC replay disagree");
    }
    std::cout << std::setprecision(17)
              << "synthetic_graph funds=" << graph.fund_ids().size()
              << " securities=" << graph.security_ids().size() << " edges=" << graph.edge_count()
              << " queue_capacity=1024 warmup_events=" << warmup << '\n';
    print_replay("sequential", serial);
    print_replay("spsc", concurrent);
}

} // namespace

int main(int argc, char** argv) {
    std::cout.imbue(std::locale::classic());
    try {
        if (argc == 1 || (argc == 2 && std::string(argv[1]) == "--help")) {
            usage(std::cout);
            return 0;
        }
        const std::string command = argv[1];
        if (command == "shock") {
            shock_command(argc, argv);
        } else if (command == "snapshot-save") {
            snapshot_save(argc, argv);
        } else if (command == "snapshot-info" && argc == 3) {
            snapshot_info(argv[2]);
        } else if (command == "demo" && argc == 2) {
            demo_command();
        } else if (command == "replay" && argc <= 3) {
            replay_command(argc == 3 ? count(argv[2]) : 200000);
        } else {
            throw std::invalid_argument("Unknown command or unexpected argument");
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        return 2;
    }
}
