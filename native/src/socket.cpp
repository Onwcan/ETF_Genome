#include "etf_genome/network/socket.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <poll.h>
#include <pthread.h>
#include <sched.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <utility>

namespace etf_genome::network {

UniqueFd::~UniqueFd() { reset(); }
UniqueFd::UniqueFd(UniqueFd&& other) noexcept : descriptor_(other.release()) {}
UniqueFd& UniqueFd::operator=(UniqueFd&& other) noexcept {
    if (this != &other) reset(other.release());
    return *this;
}
int UniqueFd::release() noexcept { return std::exchange(descriptor_, -1); }
void UniqueFd::reset(int descriptor) noexcept {
    if (descriptor_ == descriptor) return;
    const auto previous = std::exchange(descriptor_, descriptor);
    if (previous >= 0) ::close(previous);
}

SocketError::SocketError(std::string operation, int error, std::string context)
    : std::runtime_error(operation + " (" + context + "): " + std::strerror(error)),
      error_(error), operation_(std::move(operation)) {}

LoopbackListener::LoopbackListener(UniqueFd descriptor, std::uint16_t port) noexcept
    : descriptor_(std::move(descriptor)), port_(port) {}

namespace {
UniqueFd make_socket() {
    // SOCK_NONBLOCK sets O_NONBLOCK atomically; CLOEXEC prevents inheritance.
    UniqueFd descriptor(::socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0));
    if (!descriptor) throw SocketError("socket", errno, "loopback TCP");
    return descriptor;
}
sockaddr_in address(std::uint16_t port) noexcept {
    sockaddr_in value{};
    value.sin_family = AF_INET;
    value.sin_port = htons(port);
    value.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    return value;
}
} // namespace

LoopbackListener listen_loopback(std::uint16_t port) {
    auto descriptor = make_socket();
    const int reuse = 1;
    if (::setsockopt(descriptor.get(), SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) < 0)
        throw SocketError("setsockopt", errno, "SO_REUSEADDR");
    auto endpoint = address(port);
    if (::bind(descriptor.get(), reinterpret_cast<sockaddr*>(&endpoint), sizeof(endpoint)) < 0)
        throw SocketError("bind", errno, "127.0.0.1:" + std::to_string(port));
    if (::listen(descriptor.get(), 1) < 0) throw SocketError("listen", errno, "loopback TCP");
    socklen_t length = sizeof(endpoint);
    if (::getsockname(descriptor.get(), reinterpret_cast<sockaddr*>(&endpoint), &length) < 0)
        throw SocketError("getsockname", errno, "listener port");
    return LoopbackListener(std::move(descriptor), ntohs(endpoint.sin_port));
}

UniqueFd connect_loopback(std::uint16_t port, int timeout_ms, std::stop_token stop) {
    if (port == 0 || timeout_ms <= 0)
        throw std::invalid_argument("connect requires a nonzero port and positive timeout");
    auto descriptor = make_socket();
    auto endpoint = address(port);
    if (::connect(descriptor.get(), reinterpret_cast<sockaddr*>(&endpoint), sizeof(endpoint)) == 0)
        return descriptor;
    if (errno != EINPROGRESS && errno != EINTR)
        throw SocketError("connect", errno, "127.0.0.1:" + std::to_string(port));
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    while (!stop.stop_requested()) {
        const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
            deadline - std::chrono::steady_clock::now()).count();
        if (remaining <= 0) throw SocketError("connect", ETIMEDOUT, "loopback connection deadline");
        pollfd event{descriptor.get(), POLLOUT, 0};
        const auto ready = ::poll(&event, 1, static_cast<int>(std::min<std::int64_t>(remaining, 50)));
        if (ready < 0) {
            if (errno == EINTR) continue;
            throw SocketError("poll", errno, "nonblocking connect");
        }
        if (ready == 0) continue;
        int error = 0;
        socklen_t size = sizeof(error);
        if (::getsockopt(descriptor.get(), SOL_SOCKET, SO_ERROR, &error, &size) < 0)
            throw SocketError("getsockopt", errno, "connect SO_ERROR");
        if (error != 0) throw SocketError("connect", error, "loopback SO_ERROR");
        return descriptor;
    }
    throw SocketError("connect", ECANCELED, "stop requested");
}

int accept_nonblocking(int listener) noexcept {
    return ::accept4(listener, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
}

int pin_current_thread(int cpu) noexcept {
    if (cpu == -1) return 0;
    if (cpu < 0 || cpu >= CPU_SETSIZE) return EINVAL;
    cpu_set_t allowed;
    CPU_ZERO(&allowed);
    const auto get_error = ::pthread_getaffinity_np(::pthread_self(), sizeof(allowed), &allowed);
    if (get_error != 0) return get_error;
    if (!CPU_ISSET(cpu, &allowed)) return EINVAL;
    cpu_set_t selected;
    CPU_ZERO(&selected);
    CPU_SET(cpu, &selected);
    return ::pthread_setaffinity_np(::pthread_self(), sizeof(selected), &selected);
}

} // namespace etf_genome::network
