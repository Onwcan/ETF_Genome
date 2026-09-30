#include "etf_genome/market/decoder.hpp"
#include "etf_genome/core/clock.hpp"

#include <algorithm>
#include <cstring>

namespace etf_genome {

DecodeResult IncrementalDecoder::feed(std::span<const std::byte> bytes, MessageSink sink,
                                      void* context) noexcept {
    DecodeResult result;
    if (error_ != ProtocolError::None) {
        result.error = error_;
        return result;
    }
    if (sink == nullptr) {
        result.error = ProtocolError::InvalidSink;
        return result;
    }
    while (true) {
        if (ready_) {
            if (!sink(context, pending_)) {
                result.error = ProtocolError::SinkStopped;
                return result;
            }
            ++result.frames;
            used_ = 0;
            target_ = protocol_header_size;
            header_valid_ = false;
            ready_ = false;
        }
        if (result.bytes_consumed == bytes.size()) {
            return result;
        }
        const auto copied = std::min(target_ - used_, bytes.size() - result.bytes_consumed);
        std::memcpy(buffer_.data() + used_, bytes.data() + result.bytes_consumed, copied);
        used_ += copied;
        result.bytes_consumed += copied;
        if (used_ != target_) {
            continue;
        }
        if (!header_valid_) {
            FrameHeader header;
            error_ = decode_header(std::span<const std::byte>{buffer_.data(), protocol_header_size},
                                   header);
            if (error_ != ProtocolError::None) {
                result.error = error_;
                return result;
            }
            header_valid_ = true;
            target_ = protocol_header_size + header.payload_length;
            if (used_ != target_) {
                continue;
            }
        }
        error_ = decode_frame(std::span<const std::byte>{buffer_.data(), used_}, pending_);
        if (error_ != ProtocolError::None) {
            result.error = error_;
            return result;
        }
        pending_.decoded_timestamp_ns = monotonic_now_ns();
        ready_ = true;
    }
}

ProtocolError IncrementalDecoder::finish() const noexcept {
    if (error_ != ProtocolError::None) {
        return error_;
    }
    if (ready_) {
        return ProtocolError::SinkStopped;
    }
    return used_ == 0 ? ProtocolError::None : ProtocolError::TruncatedFrame;
}

void IncrementalDecoder::reset() noexcept {
    used_ = 0;
    target_ = protocol_header_size;
    header_valid_ = false;
    ready_ = false;
    pending_ = {};
    error_ = ProtocolError::None;
}

} // namespace etf_genome
