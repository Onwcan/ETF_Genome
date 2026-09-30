#include "etf_genome/network/feed.hpp"

#include <atomic>
#include <charconv>
#include <chrono>
#include <csignal>
#include <exception>
#include <iostream>
#include <stdexcept>
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
} // namespace

int main(int argc, char** argv) {
    try {
        etf_genome::network::FeedServerConfig config;
        for (int index = 1; index < argc; ++index) {
            const std::string_view flag(argv[index]);
            if (flag == "--help") {
                std::cout << "Synthetic loopback feed: --port N --events N --rate N --seed N "
                             "--instruments N --producer-cpu N --timeout-ms N --send-chunk N\n";
                return 0;
            }
            if (++index == argc) throw std::invalid_argument("missing command-line value");
            const std::string_view value(argv[index]);
            if (flag == "--port") config.port = number<std::uint16_t>(value);
            else if (flag == "--events") config.events = number<std::uint64_t>(value);
            else if (flag == "--rate") config.rate_per_second = number<std::uint64_t>(value);
            else if (flag == "--seed") config.seed = number<std::uint32_t>(value);
            else if (flag == "--instruments") config.instruments = number<std::uint32_t>(value);
            else if (flag == "--producer-cpu") config.producer_cpu = number<int>(value);
            else if (flag == "--timeout-ms") config.idle_timeout_ms = number<int>(value);
            else if (flag == "--send-chunk") config.send_chunk_bytes = number<std::size_t>(value);
            else throw std::invalid_argument("unknown command-line option");
        }
        install_signals();
        auto listener = etf_genome::network::listen_loopback(config.port);
        std::cout << "synthetic listener=127.0.0.1:" << listener.port()
                  << " events=" << config.events << " rate=" << config.rate_per_second
                  << " instruments=" << config.instruments << " seed=" << config.seed << '\n' << std::flush;
        std::stop_source shutdown;
        std::atomic<bool> done{false};
        etf_genome::network::ServerResult result;
        std::exception_ptr failure;
        std::jthread worker([&] {
            try { result = etf_genome::network::run_feed_server(listener, config, shutdown.get_token()); }
            catch (const std::exception&) { failure = std::current_exception(); }
            done.store(true, std::memory_order_release);
        });
        // The signal handler only sets a sig_atomic_t flag. Main owns shutdown.
        while (!done.load(std::memory_order_acquire)) {
            if (interrupted != 0) shutdown.request_stop();
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        worker.join();
        if (failure) std::rethrow_exception(failure);
        std::cout << "sent_messages=" << result.sent_messages << " price_updates=" << result.price_updates
                  << " bytes=" << result.bytes << " elapsed_seconds=" << result.elapsed_seconds
                  << " stopped=" << result.stopped
                  << " error=" << etf_genome::network::feed_error_name(result.error)
                  << " errno=" << result.system_error << " operation=" << result.operation << '\n';
        return result.error == etf_genome::network::FeedError::None ? 0 : 1;
    } catch (const etf_genome::network::SocketError& error) {
        std::cerr << "feed server: " << error.what() << " errno=" << error.code() << '\n';
        return 1;
    } catch (const std::exception& error) {
        std::cerr << "feed server: " << error.what() << '\n';
        return 1;
    }
}
