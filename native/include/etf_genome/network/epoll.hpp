#pragma once

#include "etf_genome/network/socket.hpp"

#include <cstdint>
#include <span>
#include <sys/epoll.h>

namespace etf_genome::network {

// Level-triggered: callers bound work per wakeup and unread data remains ready.
// No EPOLLET is used, so a fixed work budget cannot strand a readable socket.
class Epoll {
public:
    Epoll();
    void add(int descriptor, std::uint32_t events);
    void modify(int descriptor, std::uint32_t events);
    // EINTR produces zero events; other failures return -1 and preserve errno.
    [[nodiscard]] int wait(std::span<epoll_event> events, int timeout_ms) noexcept;
private:
    UniqueFd descriptor_;
};

} // namespace etf_genome::network
