#pragma once

#include <cstdint>
#include <stdexcept>
#include <stop_token>
#include <string>

namespace etf_genome::network {

// Linux descriptors have one owner. close() is never retried: after EINTR the
// descriptor may already have been released and reused by another thread.
class UniqueFd {
public:
    explicit UniqueFd(int descriptor = -1) noexcept : descriptor_(descriptor) {}
    ~UniqueFd();
    UniqueFd(const UniqueFd&) = delete;
    UniqueFd& operator=(const UniqueFd&) = delete;
    UniqueFd(UniqueFd&& other) noexcept;
    UniqueFd& operator=(UniqueFd&& other) noexcept;
    [[nodiscard]] int get() const noexcept { return descriptor_; }
    [[nodiscard]] explicit operator bool() const noexcept { return descriptor_ >= 0; }
    [[nodiscard]] int release() noexcept;
    void reset(int descriptor = -1) noexcept;
private:
    int descriptor_;
};

class SocketError : public std::runtime_error {
public:
    SocketError(std::string operation, int error, std::string context);
    [[nodiscard]] int code() const noexcept { return error_; }
    [[nodiscard]] const std::string& operation() const noexcept { return operation_; }
private:
    int error_;
    std::string operation_;
};

class LoopbackListener {
public:
    LoopbackListener(UniqueFd descriptor, std::uint16_t port) noexcept;
    [[nodiscard]] int descriptor() const noexcept { return descriptor_.get(); }
    [[nodiscard]] std::uint16_t port() const noexcept { return port_; }
private:
    UniqueFd descriptor_;
    std::uint16_t port_;
};

// The endpoint is always 127.0.0.1. Port zero selects an ephemeral test port.
[[nodiscard]] LoopbackListener listen_loopback(std::uint16_t port);
[[nodiscard]] UniqueFd connect_loopback(std::uint16_t port, int timeout_ms,
                                        std::stop_token stop = {});
// Returns -1 with errno preserved on EAGAIN/EINTR or another accept failure.
[[nodiscard]] int accept_nonblocking(int listener) noexcept;
// -1 means off; otherwise the CPU must be in this thread's allowed CPU mask.
[[nodiscard]] int pin_current_thread(int cpu) noexcept;

} // namespace etf_genome::network
