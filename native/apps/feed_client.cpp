#include "etf_genome/csv.hpp"
#include "etf_genome/exposure.hpp"
#include "etf_genome/network/feed.hpp"
#include "etf_genome/risk/price_exposure.hpp"
#include "etf_genome/risk/snapshot.hpp"

#include <algorithm>
#include <atomic>
#include <charconv>
#include <chrono>
#include <csignal>
#include <exception>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <locale>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>

namespace {
volatile std::sig_atomic_t interrupted = 0;
extern "C" void handle_signal(int) { interrupted = 1; }

void install_signals() {
    struct sigaction action{};
    action.sa_handler = handle_signal;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, nullptr) != 0 || sigaction(SIGTERM, &action, nullptr) != 0)
        throw std::runtime_error("cannot install shutdown signal handlers");
}

template <typename T>
T number(std::string_view value) {
    T result{};
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
    if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size())
        throw std::invalid_argument("invalid integer command-line value");
    return result;
}

bool consume(void* context, const etf_genome::MarketMessage& message) noexcept {
    return static_cast<etf_genome::PriceExposureEngine*>(context)->on_message(message);
}

const char* exposure_error_name(etf_genome::PriceError error) noexcept {
    switch (error) {
    case etf_genome::PriceError::None: return "none";
    case etf_genome::PriceError::InvalidInstrument: return "invalid_instrument";
    case etf_genome::PriceError::InvalidPrice: return "invalid_price";
    case etf_genome::PriceError::SnapshotMismatch: return "snapshot_mismatch";
    case etf_genome::PriceError::Overflow: return "overflow";
    }
    return "unknown";
}

void print_latency(const char* name, const etf_genome::LatencyHistogram& histogram) {
    std::cout << name << "_ns p50=" << histogram.percentile(50)
              << " p90=" << histogram.percentile(90) << " p95=" << histogram.percentile(95)
              << " p99=" << histogram.percentile(99) << " p99.9=" << histogram.percentile(99.9)
              << " max=" << histogram.max() << '\n';
}
} // namespace

int main(int argc, char** argv) {
    std::cout.imbue(std::locale::classic());
    std::cout << std::setprecision(17);
    try {
        etf_genome::network::FeedClientConfig config;
        std::uint32_t instruments = 1024;
        bool explicit_instruments = false;
        std::string edges;
        std::string snapshot;
        for (int index = 1; index < argc; ++index) {
            const std::string_view flag(argv[index]);
            if (flag == "--help") {
                std::cout << "Synthetic loopback client: --port N --instruments N "
                             "[--edges CSV | --snapshot BINARY] --producer-cpu N --consumer-cpu N "
                             "--timeout-ms N --consumer-delay-us N\n"
                             "Synthetic instruments: 1 through 100000. Imported graphs determine "
                             "the instrument count; an explicit --instruments must match.\n"
                             "Feed instrument IDs index the graph's sorted security IDs.\n";
                return 0;
            }
            if (++index == argc) throw std::invalid_argument("missing command-line value");
            const std::string_view value(argv[index]);
            if (flag == "--port") config.port = number<std::uint16_t>(value);
            else if (flag == "--instruments") {
                instruments = number<std::uint32_t>(value);
                explicit_instruments = true;
            }
            else if (flag == "--edges") edges = value;
            else if (flag == "--snapshot") snapshot = value;
            else if (flag == "--producer-cpu") config.producer_cpu = number<int>(value);
            else if (flag == "--consumer-cpu") config.consumer_cpu = number<int>(value);
            else if (flag == "--timeout-ms") {
                config.idle_timeout_ms = number<int>(value);
                config.connect_timeout_ms = config.idle_timeout_ms;
            } else if (flag == "--consumer-delay-us") config.consumer_delay_us = number<std::uint32_t>(value);
            else throw std::invalid_argument("unknown command-line option");
        }
        if (!edges.empty() && !snapshot.empty())
            throw std::invalid_argument("use only one of --edges and --snapshot");
        const auto graph = [&] {
            if (edges.empty() && snapshot.empty()) {
                if (instruments == 0 || instruments > 100000)
                    throw std::invalid_argument("synthetic instrument count must be 1 through 100000");
                // Generator fund ranges start 13 securities apart. Enough funds
                // ensure their overlapping ranges cover every requested index.
                const auto funds = std::max<std::size_t>(128,
                    (static_cast<std::size_t>(instruments) + 12) / 13);
                auto synthetic = etf_genome::make_synthetic_graph(
                    funds, instruments, std::min<std::size_t>(64, instruments));
                if (synthetic.security_ids().size() != instruments)
                    throw std::runtime_error("synthetic graph does not cover all feed instruments");
                return synthetic;
            }
            std::ifstream input(snapshot.empty() ? edges : snapshot, std::ios::binary);
            if (!input) throw std::runtime_error("cannot open exposure graph input");
            return snapshot.empty()
                ? etf_genome::ExposureGraph(etf_genome::read_holdings_csv(input))
                : etf_genome::read_binary_snapshot(input);
        }();
        if (graph.security_ids().empty())
            throw std::invalid_argument("feed graph must contain at least one security");
        if (explicit_instruments && graph.security_ids().size() != instruments)
            throw std::invalid_argument("--instruments does not match imported graph security count");
        etf_genome::PriceExposureEngine engine(graph);
        install_signals();
        std::cout << "synthetic connection=127.0.0.1:" << config.port
                  << " securities=" << graph.security_ids().size() << " funds=" << graph.fund_ids().size()
                  << " edges=" << graph.edge_count() << " queue_capacity="
                  << etf_genome::network::feed_queue_capacity << '\n' << std::flush;
        std::stop_source shutdown;
        std::atomic<bool> done{false};
        etf_genome::network::FeedResult result;
        std::exception_ptr failure;
        std::jthread worker([&] {
            try { result = etf_genome::network::run_feed_client(config, consume, &engine, shutdown.get_token()); }
            catch (const std::exception&) { failure = std::current_exception(); }
            done.store(true, std::memory_order_release);
        });
        while (!done.load(std::memory_order_acquire)) {
            if (interrupted != 0) shutdown.request_stop();
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        worker.join();
        if (failure) std::rethrow_exception(failure);
        const auto seconds = result.elapsed_seconds;
        std::cout << "decoded_messages=" << result.decoded_messages << " processed_messages="
                  << result.processed_messages << " price_updates=" << result.price_updates
                  << " bytes=" << result.bytes << " elapsed_seconds=" << seconds
                  << " messages_per_second=" << (seconds > 0 ? static_cast<double>(result.processed_messages) / seconds : 0)
                  << " bytes_per_second=" << (seconds > 0 ? static_cast<double>(result.bytes) / seconds : 0)
                  << " queue_full_events=" << result.queue_full_events
                  << " decode_errors=" << result.decode_errors
                  << " invalid_timestamps=" << result.invalid_timestamps
                  << " sequence_gaps=" << result.sequence_gaps
                  << " duplicates=" << result.duplicates << " out_of_order=" << result.out_of_order
                  << " checksum=" << engine.checksum() << " stopped=" << result.stopped
                  << " error=" << etf_genome::network::feed_error_name(result.error)
                  << " exposure_error=" << exposure_error_name(engine.error())
                  << " protocol_error=" << etf_genome::protocol_error_name(result.protocol_error)
                  << " errno=" << result.system_error << " operation=" << result.operation << '\n';
        print_latency("transport", result.transport_latency);
        print_latency("queue", result.queue_latency);
        print_latency("processing", result.processing_latency);
        print_latency("end_to_end", result.end_to_end_latency);
        return result.error == etf_genome::network::FeedError::None ? 0 : 1;
    } catch (const etf_genome::network::SocketError& error) {
        std::cerr << "feed client: " << error.what() << " errno=" << error.code() << '\n';
        return 1;
    } catch (const std::exception& error) {
        std::cerr << "feed client: " << error.what() << '\n';
        return 1;
    }
}
