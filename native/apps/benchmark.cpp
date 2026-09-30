#include "allocation_counter.hpp"
#include "etf_genome/core/clock.hpp"
#include "etf_genome/market/decoder.hpp"
#include "etf_genome/metrics/histogram.hpp"
#include "etf_genome/risk/price_exposure.hpp"
#include "etf_genome/spsc_queue.hpp"
#if defined(ETF_GENOME_HAS_NETWORK)
#include "etf_genome/network/feed.hpp"
#endif
#if defined(ETF_GENOME_PLATFORM_LINUX)
#include <cerrno>
#include <pthread.h>
#include <sched.h>
#include <sys/utsname.h>
#endif

#include <algorithm>
#include <atomic>
#include <charconv>
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
using namespace etf_genome;
using namespace etf_genome::benchmark;
struct Config {
    std::string mode = "all";
    std::uint64_t events = 100000;
    bool count_allocations = false;
    bool self_check_only = false;
    int producer_cpu = -1, consumer_cpu = -1;
};
struct Sample {
    const char* name = "";
    const char* allocation_scope = "";
    const char* latency_scope = "";
    const char* events_unit = "price_messages";
    std::uint64_t events = 0, bytes = 0, full = 0, allocation_calls = 0;
    std::uint64_t invalid_timestamps = 0;
    double seconds = 0, checksum = 0;
    LatencyHistogram latency;
};

constexpr bool performance_eligible = std::string_view{ETF_GENOME_BUILD_TYPE} == "Release";

// Benchmark-only Linux setup: the portable queue does not acquire an OS dependency.
int pin_benchmark_thread(int cpu) noexcept {
#if defined(ETF_GENOME_PLATFORM_LINUX)
    if (cpu == -1) { return 0; }
    if (cpu < 0 || cpu >= CPU_SETSIZE) { return EINVAL; }
    cpu_set_t allowed;
    CPU_ZERO(&allowed);
    const auto current = ::pthread_getaffinity_np(::pthread_self(), sizeof(allowed), &allowed);
    if (current != 0) { return current; }
    if (!CPU_ISSET(cpu, &allowed)) { return EINVAL; }
    cpu_set_t selected;
    CPU_ZERO(&selected);
    CPU_SET(cpu, &selected);
    return ::pthread_setaffinity_np(::pthread_self(), sizeof(selected), &selected);
#else
    return cpu == -1 ? 0 : 1;
#endif
}

void record_latency(Sample& sample, std::uint64_t started, std::uint64_t finished) noexcept {
    if (started == 0 || finished == 0 || finished < started) {
        ++sample.invalid_timestamps;
        return;
    }
    sample.latency.record(finished - started);
}

double elapsed_seconds(std::uint64_t started, std::uint64_t finished) {
    if (started == 0 || finished == 0 || finished < started) {
        throw std::runtime_error("Monotonic clock returned an invalid duration");
    }
    return static_cast<double>(finished - started) / 1e9;
}

std::uint64_t integer(const std::string& text) {
    std::uint64_t value = 0;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size()) {
        throw std::invalid_argument("Numeric options must be unsigned integers");
    }
    return value;
}

std::string quoted(const std::string& input) {
    std::string result = "\"";
    for (const auto character : input) {
        if (character == '"' || character == '\\') { result.push_back('\\'); }
        if (static_cast<unsigned char>(character) >= 32) { result.push_back(character); }
    }
    result.push_back('"');
    return result;
}

void histogram(const LatencyHistogram& hist) {
    std::cout << "{\"count\":" << hist.count() << ",\"p50_ns\":" << hist.percentile(50)
              << ",\"p90_ns\":" << hist.percentile(90) << ",\"p95_ns\":" << hist.percentile(95)
              << ",\"p99_ns\":" << hist.percentile(99) << ",\"p999_ns\":" << hist.percentile(99.9)
              << ",\"max_ns\":" << hist.max() << '}';
}

void print_sample(const Sample& sample, bool measured) {
    if (sample.invalid_timestamps != 0) {
        throw std::runtime_error("Benchmark observed invalid latency timestamps");
    }
    std::cout << "{\"benchmark\":" << quoted(sample.name) << ",\"events\":" << sample.events
              << ",\"events_unit\":" << quoted(sample.events_unit)
              << ",\"seconds\":" << sample.seconds << ",\"messages_per_second\":"
              << (sample.seconds > 0 ? static_cast<double>(sample.events) / sample.seconds : 0)
              << ",\"bytes_per_second\":"
              << (sample.seconds > 0 ? static_cast<double>(sample.bytes) / sample.seconds : 0)
              << ",\"queue_full_attempts\":" << sample.full << ",\"checksum\":" << sample.checksum
              << ",\"performance_eligible\":" << (performance_eligible ? "true" : "false")
              << ",\"invalid_timestamps\":" << sample.invalid_timestamps
              << ",\"allocation_measurement\":" << (measured ? "true" : "false")
              << ",\"operator_new_calls\":" << sample.allocation_calls << ",\"latency\":";
    histogram(sample.latency);
    std::cout << ",\"allocation_scope\":" << quoted(sample.allocation_scope)
              << ",\"latency_scope\":" << quoted(sample.latency_scope);
    std::cout << "}\n";
}

MarketMessage price_message(std::uint64_t index, std::size_t securities) {
    MarketMessage message{};
    message.type = MessageType::PriceUpdate;
    message.sequence = index;
    message.instrument_id = static_cast<std::uint32_t>(index % securities);
    message.price_ticks = 100000 + static_cast<std::int64_t>((index / securities) % 201) - 100;
    message.quantity = 1;
    return message;
}

Sample queue_benchmark(std::uint64_t events, bool track, const Config& config) {
    SpscQueue<MarketMessage, 1024> queue;
    Sample sample;
    sample.name = "spsc";
    sample.allocation_scope = "producer and consumer event loops; excludes thread startup and reporting";
    sample.latency_scope = "producer timestamp through consumer pop; includes queue wait and backpressure";
    std::atomic<bool> ready{false};
    std::atomic<unsigned> initialized{0};
    std::atomic<bool> producer_done{false}, cancelled{false};
    std::uint64_t retries = 0;
    std::uint64_t finished = 0;
    int producer_affinity_error = 0, consumer_affinity_error = 0;
    bool order_valid = true;
    reset_allocations();
    std::jthread producer([&](std::stop_token stop) {
        producer_affinity_error = pin_benchmark_thread(config.producer_cpu);
        if (producer_affinity_error != 0) { cancelled.store(true, std::memory_order_release); }
        initialized.fetch_add(1, std::memory_order_release);
        while (!ready.load(std::memory_order_acquire) && !cancelled.load(std::memory_order_acquire) &&
               !stop.stop_requested()) { std::this_thread::yield(); }
        AllocationScope allocation_scope(track);
        for (std::uint64_t index = 0; index < events && !stop.stop_requested() &&
             !cancelled.load(std::memory_order_acquire); ++index) {
            auto message = price_message(index, 1024);
            message.send_timestamp_ns = monotonic_now_ns();
            while (!queue.try_push(message)) {
                ++retries;
                if (stop.stop_requested() || cancelled.load(std::memory_order_acquire)) { break; }
                std::this_thread::yield();
            }
        }
        producer_done.store(true, std::memory_order_release);
    });
    // Each worker owns its affinity. The main thread and later single-thread
    // benchmarks retain their original mask. jthread unwinding stops the producer
    // if consumer thread construction fails before the start barrier opens.
    std::jthread consumer([&](std::stop_token stop) {
        consumer_affinity_error = pin_benchmark_thread(config.consumer_cpu);
        if (consumer_affinity_error != 0) { cancelled.store(true, std::memory_order_release); }
        initialized.fetch_add(1, std::memory_order_release);
        while (!ready.load(std::memory_order_acquire) && !cancelled.load(std::memory_order_acquire) &&
               !stop.stop_requested()) { std::this_thread::yield(); }
        AllocationScope allocation_scope(track);
        MarketMessage message{};
        for (std::uint64_t expected = 0; expected < events && !stop.stop_requested() &&
             !cancelled.load(std::memory_order_acquire);) {
            if (!queue.try_pop(message)) {
                if (producer_done.load(std::memory_order_acquire)) {
                    if (!queue.try_pop(message)) { break; }
                } else {
                    std::this_thread::yield();
                    continue;
                }
            }
            if (message.sequence != expected) {
                order_valid = false;
                cancelled.store(true, std::memory_order_release);
                break;
            }
            record_latency(sample, message.send_timestamp_ns, monotonic_now_ns());
            sample.checksum += static_cast<double>(message.instrument_id);
            ++expected;
            ++sample.events;
        }
        finished = monotonic_now_ns();
    });
    while (initialized.load(std::memory_order_acquire) != 2) { std::this_thread::yield(); }
    const auto start = monotonic_now_ns();
    ready.store(true, std::memory_order_release);
    consumer.join();
    producer.join();
    if (producer_affinity_error != 0 || consumer_affinity_error != 0) {
        throw std::runtime_error("SPSC CPU affinity failed: producer errno=" +
            std::to_string(producer_affinity_error) + ", consumer errno=" +
            std::to_string(consumer_affinity_error));
    }
    if (!order_valid || sample.events != events) {
        throw std::runtime_error("SPSC benchmark lost or reordered a message");
    }
    sample.seconds = elapsed_seconds(start, finished);
    sample.full = retries;
    sample.allocation_calls = allocations();
    return sample;
}

bool decoded(void* context, const MarketMessage& message) noexcept {
    auto& sample = *static_cast<Sample*>(context);
    sample.checksum += static_cast<double>(message.price_ticks);
    ++sample.events;
    return true;
}

Sample decoder_benchmark(std::uint64_t events, bool track) {
    IncrementalDecoder decoder;
    EncodedFrame frame;
    if (encode_message(price_message(0, 1024), frame) != ProtocolError::None) {
        throw std::runtime_error("Benchmark frame serialization failed");
    }
    Sample sample;
    sample.name = "decoder";
    sample.allocation_scope = "decoder feed, callback and latency collection inside the event loop";
    sample.latency_scope = "one feed call with a reused preencoded frame, including callback and decode clock";
    reset_allocations();
    const auto start = monotonic_now_ns();
    {
        AllocationScope allocation_scope(track);
        for (std::uint64_t index = 0; index < events; ++index) {
            const auto before = monotonic_now_ns();
            const auto result = decoder.feed(frame.view(), decoded, &sample);
            const auto after = monotonic_now_ns();
            if (result.error != ProtocolError::None || result.frames != 1) {
                throw std::runtime_error("Decoder benchmark did not accept exactly one frame");
            }
            record_latency(sample, before, after);
        }
    }
    sample.seconds = elapsed_seconds(start, monotonic_now_ns());
    sample.bytes = events * frame.size;
    sample.allocation_calls = allocations();
    return sample;
}

Sample exposure_benchmark(std::uint64_t events, bool track) {
    const auto graph = make_synthetic_graph();
    PriceExposureEngine engine(graph);
    Sample sample;
    sample.name = "exposure";
    sample.allocation_scope = "synthetic event construction, exposure update and latency collection; excludes graph setup";
    sample.latency_scope = "one price exposure update; includes initial reference-price assignments";
    reset_allocations();
    const auto start = monotonic_now_ns();
    {
        AllocationScope allocation_scope(track);
        for (std::uint64_t index = 0; index < events; ++index) {
            const auto message = price_message(index, graph.security_ids().size());
            const auto before = monotonic_now_ns();
            if (!engine.on_message(message)) {
                throw std::runtime_error("Exposure benchmark rejected a synthetic price");
            }
            record_latency(sample, before, monotonic_now_ns());
        }
    }
    sample.seconds = elapsed_seconds(start, monotonic_now_ns());
    sample.events = events;
    sample.checksum = engine.checksum();
    sample.allocation_calls = allocations();
    return sample;
}

#if defined(ETF_GENOME_HAS_NETWORK)
struct ConsumerContext { PriceExposureEngine* engine; bool track; };
bool consume(void* context, const MarketMessage& message) noexcept {
    auto& state = *static_cast<ConsumerContext*>(context);
    AllocationScope allocation_scope(state.track);
    return state.engine->on_message(message);
}

struct TcpCase { network::FeedResult received; network::ServerResult sent; };

TcpCase run_tcp_case(network::LoopbackListener& listener,
                     const network::FeedServerConfig& server_config,
                     const network::FeedClientConfig& client_config,
                     ConsumerContext& state) {
    TcpCase result;
    std::stop_source client_shutdown;
    std::exception_ptr server_failure;
    std::jthread server([&](std::stop_token stop) {
        try {
            result.sent = network::run_feed_server(listener, server_config, stop);
            if (result.sent.error != network::FeedError::None) { client_shutdown.request_stop(); }
        } catch (const std::exception&) {
            server_failure = std::current_exception();
            client_shutdown.request_stop();
        }
    });
    try {
        result.received = network::run_feed_client(client_config, consume, &state,
                                                   client_shutdown.get_token());
    } catch (const std::exception&) {
        server.request_stop();
        server.join();
        throw;
    }
    // A rejected client must not leave its server waiting for a progress timeout.
    // Both error and exception paths request stop and join before stack teardown.
    if (result.received.error != network::FeedError::None || result.received.stopped) {
        server.request_stop();
    }
    server.join();
    if (server_failure) { std::rethrow_exception(server_failure); }
    return result;
}

void validate_tcp(const TcpCase& result, std::uint64_t price_events) {
    const auto& received = result.received;
    const auto& sent = result.sent;
    if (received.error != network::FeedError::None || sent.error != network::FeedError::None ||
        received.stopped || sent.stopped || received.price_updates != price_events ||
        received.processed_messages != price_events + 3 ||
        received.decoded_messages != received.processed_messages ||
        sent.sent_messages != received.processed_messages || sent.bytes != received.bytes ||
        received.sequence_gaps || received.duplicates || received.out_of_order ||
        received.decode_errors || received.invalid_timestamps) {
        throw std::runtime_error(std::string("TCP benchmark correctness check failed: client=") +
            network::feed_error_name(received.error) + " operation=" + received.operation +
            " errno=" + std::to_string(received.system_error) + " server=" +
            network::feed_error_name(sent.error) + " operation=" + sent.operation +
            " errno=" + std::to_string(sent.system_error));
    }
}

void tcp_benchmark(const Config& config) {
    const auto graph = make_synthetic_graph();
    PriceExposureEngine engine(graph);
    auto listener = network::listen_loopback(0);
    network::FeedServerConfig server_config;
    server_config.port = listener.port();
    server_config.events = config.events;
    server_config.instruments = static_cast<std::uint32_t>(graph.security_ids().size());
    // Separate warm-up connection exercises decode, queue, and engine initialization.
    auto warm_listener = network::listen_loopback(0);
    auto warm_config = server_config;
    warm_config.events = std::min<std::uint64_t>(config.events, 10000);
    warm_config.port = warm_listener.port();
    network::FeedClientConfig client_config;
    client_config.port = warm_listener.port();
    client_config.producer_cpu = config.producer_cpu;
    client_config.consumer_cpu = config.consumer_cpu;
    ConsumerContext state{&engine, false};
    const auto warmed = run_tcp_case(warm_listener, warm_config, client_config, state);
    validate_tcp(warmed, warm_config.events);
    engine.reset();
    state.track = config.count_allocations;
    reset_allocations();
    client_config.port = listener.port();
    const auto measured = run_tcp_case(listener, server_config, client_config, state);
    validate_tcp(measured, config.events);
    const auto& result = measured.received;
    Sample sample;
    sample.name = "tcp";
    sample.allocation_scope = "consumer exposure callback only; excludes network, decoder, queue and thread setup";
    sample.latency_scope = "synthetic same-host send timestamp through consumer callback completion";
    sample.events_unit = "decoded_messages_including_three_control_frames";
    sample.events = result.processed_messages;
    sample.bytes = result.bytes;
    sample.seconds = result.elapsed_seconds;
    sample.full = result.queue_full_events;
    sample.checksum = engine.checksum();
    sample.allocation_calls = allocations();
    sample.latency = result.end_to_end_latency;
    print_sample(sample, config.count_allocations);
    std::cout << "{\"benchmark\":\"tcp_stages\",\"price_updates\":" << result.price_updates
              << ",\"decode_errors\":" << result.decode_errors << ",\"sequence_gaps\":" << result.sequence_gaps
              << ",\"duplicates\":" << result.duplicates << ",\"out_of_order\":" << result.out_of_order
              << ",\"invalid_timestamps\":" << result.invalid_timestamps
              << ",\"allocation_scope\":\"consumer exposure callback only; whole TCP allocation behavior is not measured\""
              << ",\"transport\":";
    histogram(result.transport_latency);
    std::cout << ",\"queue\":"; histogram(result.queue_latency);
    std::cout << ",\"processing\":"; histogram(result.processing_latency);
    std::cout << "}\n";
}
#endif

void environment(const Config& config) {
    std::string os = "portable", kernel, cpu = "not collected", machine = "not collected";
#if defined(ETF_GENOME_PLATFORM_LINUX)
    utsname system{};
    if (::uname(&system) == 0) {
        os = system.sysname; kernel = system.release; machine = system.machine;
    }
    std::ifstream processor("/proc/cpuinfo");
    std::string line;
    while (std::getline(processor, line)) {
        if (line.starts_with("model name")) {
            const auto separator = line.find(':');
            if (separator != std::string::npos) { cpu = line.substr(separator + 2); }
            break;
        }
    }
#elif defined(ETF_GENOME_PLATFORM_WINDOWS)
    os = "Windows";
#endif
    std::cout << "{\"environment\":{\"os\":" << quoted(os) << ",\"kernel\":" << quoted(kernel)
              << ",\"machine\":" << quoted(machine)
              << ",\"cpu\":" << quoted(cpu) << ",\"logical_cpus\":" << std::thread::hardware_concurrency()
              << ",\"compiler\":" << quoted(ETF_GENOME_COMPILER_ID)
              << ",\"compiler_version\":" << quoted(ETF_GENOME_COMPILER_VERSION)
              << ",\"build_type\":" << quoted(ETF_GENOME_BUILD_TYPE)
              << ",\"optimization_flags\":" << quoted(ETF_GENOME_OPTIMIZATION_FLAGS)
#if defined(ETF_GENOME_COMPILE_FLAGS)
              << ",\"compile_flags\":" << quoted(ETF_GENOME_COMPILE_FLAGS)
#else
              << ",\"compile_flags\":\"not captured; consult compile_commands.json\""
#endif
              << ",\"performance_eligible\":" << (performance_eligible ? "true" : "false")
              << ",\"performance_note\":\"Only Release runs are performance results; Debug runs are correctness smoke checks\""
              << ",\"cxx_standard\":20,\"events_requested\":" << config.events
              << ",\"queue_capacity\":1024,\"price_frame_bytes\":48,\"producer_cpu\":" << config.producer_cpu
              << ",\"consumer_cpu\":" << config.consumer_cpu
              << ",\"affinity_scope\":\"SPSC workers and TCP client workers only; decoder, exposure, main and TCP server unpinned\""
              << ",\"warmup_events\":" << std::min<std::uint64_t>(config.events, 10000)
              << ",\"instrumentation_enabled\":" << (config.count_allocations ? "true" : "false")
              << ",\"allocation_hook_scope\":\"successful replacement C++ operator new calls in enabled thread-local scopes; excludes direct malloc/calloc/realloc, mmap and external allocator internals\""
              << ",\"decoder_reuses_one_preencoded_frame\":true,\"tcp_control_frames\":3"
#if defined(ETF_GENOME_HAS_NETWORK)
              << ",\"network_available\":true"
#else
              << ",\"network_available\":false"
#endif
              ;
#if defined(ETF_GENOME_PLATFORM_LINUX)
    cpu_set_t allowed;
    CPU_ZERO(&allowed);
    if (::pthread_getaffinity_np(::pthread_self(), sizeof(allowed), &allowed) == 0) {
        std::cout << ",\"allowed_cpus\":[";
        bool first = true;
        for (int cpu_id = 0; cpu_id < CPU_SETSIZE; ++cpu_id) {
            if (!CPU_ISSET(cpu_id, &allowed)) { continue; }
            if (!first) { std::cout << ','; }
            std::cout << cpu_id;
            first = false;
        }
        std::cout << ']';
    }
#endif
    std::cout << "}}\n";
}
}

int main(int argc, char** argv) {
    std::cout.imbue(std::locale::classic());
    std::cout << std::setprecision(17);
    try {
        Config config;
        for (int index = 1; index < argc; ++index) {
            const std::string option = argv[index];
            if (option == "--allocations") { config.count_allocations = true; continue; }
            if (option == "--self-check") { config.self_check_only = true; continue; }
            if (option == "--help") {
                std::cout << "etf-genome-benchmark --mode all|spsc|decoder|exposure|tcp --events N [--allocations] [--producer-cpu N --consumer-cpu N]\n"
                          << "CPU affinity applies to SPSC and TCP client workers on Linux only.\n"
                          << "etf-genome-benchmark --self-check verifies allocation hooks without timing.\n";
                return 0;
            }
            if (++index >= argc) { throw std::invalid_argument("Option requires a value"); }
            if (option == "--mode") { config.mode = argv[index]; }
            else if (option == "--events") { config.events = integer(argv[index]); }
            else if (option == "--producer-cpu" || option == "--consumer-cpu") {
                const auto cpu = integer(argv[index]);
                if (cpu > 65535) { throw std::invalid_argument("CPU id exceeds supported range"); }
                (option == "--producer-cpu" ? config.producer_cpu : config.consumer_cpu) = static_cast<int>(cpu);
            } else { throw std::invalid_argument("Unknown benchmark option"); }
        }
        if (config.events == 0 || config.events > 10000000) { throw std::invalid_argument("Events must be 1 through 10000000"); }
        if (config.mode != "all" && config.mode != "spsc" && config.mode != "decoder" && config.mode != "exposure" && config.mode != "tcp") {
            throw std::invalid_argument("Unknown benchmark mode");
        }
        const bool affinity_requested = config.producer_cpu != -1 || config.consumer_cpu != -1;
        if (affinity_requested && (config.self_check_only ||
            (config.mode != "all" && config.mode != "spsc" && config.mode != "tcp"))) {
            throw std::invalid_argument("CPU affinity is supported only for SPSC and TCP benchmark workers");
        }
#if !defined(ETF_GENOME_PLATFORM_LINUX)
        if (affinity_requested) { throw std::invalid_argument("CPU affinity requires Linux"); }
#endif
#if !defined(ETF_GENOME_HAS_NETWORK)
        if (config.mode == "tcp") { throw std::invalid_argument("TCP benchmark requires a Linux network build"); }
#endif
        if (config.count_allocations || config.self_check_only) {
            const auto self_check = allocation_counter_self_check();
            std::cout << "{\"allocation_counter_self_check\":{\"passed\":"
                      << (self_check.passed() ? "true" : "false") << ",\"observed_calls\":"
                      << self_check.observed_calls << ",\"expected_calls\":" << self_check.expected_calls
                      << ",\"method\":\"explicit volatile function-pointer calls; scalar, array, aligned, nothrow, nested and thread-local scope checks\"}}\n";
            if (!self_check.passed()) { throw std::runtime_error("Allocation counter self-check failed"); }
            if (config.self_check_only) { return 0; }
        }
        environment(config);
        const auto warmup = std::min<std::uint64_t>(config.events, 10000);
        if (config.mode == "all" || config.mode == "spsc") {
            (void)queue_benchmark(warmup, false, config);
            print_sample(queue_benchmark(config.events, config.count_allocations, config), config.count_allocations);
        }
        if (config.mode == "all" || config.mode == "decoder") {
            (void)decoder_benchmark(warmup, false);
            print_sample(decoder_benchmark(config.events, config.count_allocations), config.count_allocations);
        }
        if (config.mode == "all" || config.mode == "exposure") {
            (void)exposure_benchmark(warmup, false);
            print_sample(exposure_benchmark(config.events, config.count_allocations), config.count_allocations);
        }
#if defined(ETF_GENOME_HAS_NETWORK)
        if (config.mode == "all" || config.mode == "tcp") { tcp_benchmark(config); }
#endif
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Benchmark error: " << error.what() << '\n';
        return 2;
    }
}
