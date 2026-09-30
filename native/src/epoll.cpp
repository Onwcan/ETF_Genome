#include "etf_genome/network/epoll.hpp"

#include <cerrno>
#include <limits>

namespace etf_genome::network {

Epoll::Epoll() : descriptor_(::epoll_create1(EPOLL_CLOEXEC)) {
    if (!descriptor_) throw SocketError("epoll_create1", errno, "level-triggered loop");
}
void Epoll::add(int descriptor, std::uint32_t events) {
    epoll_event event{};
    event.events = events;
    event.data.fd = descriptor;
    if (::epoll_ctl(descriptor_.get(), EPOLL_CTL_ADD, descriptor, &event) < 0)
        throw SocketError("epoll_ctl ADD", errno, "descriptor " + std::to_string(descriptor));
}
void Epoll::modify(int descriptor, std::uint32_t events) {
    epoll_event event{};
    event.events = events;
    event.data.fd = descriptor;
    if (::epoll_ctl(descriptor_.get(), EPOLL_CTL_MOD, descriptor, &event) < 0)
        throw SocketError("epoll_ctl MOD", errno, "descriptor " + std::to_string(descriptor));
}
int Epoll::wait(std::span<epoll_event> events, int timeout_ms) noexcept {
    if (events.empty() || events.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        errno = EINVAL;
        return -1;
    }
    const auto result = ::epoll_wait(descriptor_.get(), events.data(),
                                     static_cast<int>(events.size()), timeout_ms);
    return result < 0 && errno == EINTR ? 0 : result;
}

} // namespace etf_genome::network
