#include "etf_genome/risk/snapshot.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <istream>
#include <limits>
#include <ostream>
#include <span>
#include <stdexcept>
#include <string_view>

namespace etf_genome {
namespace {

constexpr std::size_t header_size = 64;
constexpr std::size_t max_payload = 64U * 1024U * 1024U;
constexpr std::uint32_t max_nodes = 100000;
constexpr std::uint64_t max_edges = 1000000;
constexpr std::string_view magic = "EGEXPOS1";
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);

void append(std::vector<std::uint8_t>& out, std::uint64_t value, unsigned width) {
    if (out.size() > max_payload - width) {
        throw std::invalid_argument("Binary snapshot exceeds 64 MiB");
    }
    for (unsigned index = width; index > 0; --index) {
        out.push_back(static_cast<std::uint8_t>(value >> ((index - 1U) * 8U)));
    }
}

void text(std::vector<std::uint8_t>& out, const std::string& value) {
    if (value.empty() || value.size() > 4096 || value.find('\0') != std::string::npos) {
        throw std::invalid_argument("Snapshot ids must contain 1 through 4096 non-NUL bytes");
    }
    append(out, value.size(), 4);
    if (value.size() > max_payload - out.size()) {
        throw std::invalid_argument("Binary snapshot exceeds 64 MiB");
    }
    out.insert(out.end(), value.begin(), value.end());
}

std::uint64_t checksum(std::span<const std::uint8_t> bytes) noexcept {
    std::uint64_t hash = 14695981039346656037ULL;
    for (const auto value : bytes) {
        hash ^= value;
        hash *= 1099511628211ULL;
    }
    return hash;
}

class Reader {
public:
    explicit Reader(std::span<const std::uint8_t> bytes) : bytes_(bytes) {}
    std::uint64_t integer(unsigned width) {
        if (width > bytes_.size() - position_) {
            throw std::invalid_argument("Truncated binary snapshot field");
        }
        std::uint64_t value = 0;
        for (unsigned index = 0; index < width; ++index) {
            value = (value << 8U) | bytes_[position_++];
        }
        return value;
    }
    std::string string() {
        const auto length = integer(4);
        if (length == 0 || length > 4096 || length > bytes_.size() - position_) {
            throw std::invalid_argument("Invalid binary snapshot id length");
        }
        std::string value(reinterpret_cast<const char*>(bytes_.data() + position_),
                          static_cast<std::size_t>(length));
        position_ += static_cast<std::size_t>(length);
        if (value.find('\0') != std::string::npos) {
            throw std::invalid_argument("Binary snapshot id contains NUL");
        }
        return value;
    }
    [[nodiscard]] bool exhausted() const noexcept { return position_ == bytes_.size(); }
private:
    std::span<const std::uint8_t> bytes_;
    std::size_t position_ = 0;
};

} // namespace

void write_binary_snapshot(std::ostream& output, const ExposureGraph& graph) {
    const auto data = graph.snapshot_data();
    if (data.fund_ids.size() > max_nodes || data.security_ids.size() > max_nodes ||
        data.links.size() > max_edges || data.aliases.size() > max_edges) {
        throw std::invalid_argument("Graph exceeds binary snapshot count limits");
    }
    std::size_t estimated = data.offsets.size() * 8 + data.links.size() * 16;
    auto budget_id = [&](const std::string& id, std::size_t overhead) {
        if (id.size() > 4096 || id.size() + overhead > max_payload - estimated) {
            throw std::invalid_argument("Binary snapshot exceeds field or payload limits");
        }
        estimated += id.size() + overhead;
    };
    for (const auto& id : data.fund_ids) { budget_id(id, 4); }
    for (const auto& id : data.security_ids) { budget_id(id, 4); }
    for (const auto& alias : data.aliases) { budget_id(alias.ticker, 8); }
    std::vector<std::uint8_t> payload;
    payload.reserve(estimated);
    for (const auto& id : data.fund_ids) { text(payload, id); }
    for (const auto& id : data.security_ids) { text(payload, id); }
    for (const auto& alias : data.aliases) {
        text(payload, alias.ticker);
        append(payload, alias.security_index, 4);
    }
    for (const auto offset : data.offsets) { append(payload, offset, 8); }
    for (const auto& link : data.links) {
        append(payload, link.fund_index, 4);
        append(payload, link.has_weight ? 1U : 0U, 1);
        append(payload, 0, 3);
        append(payload, std::bit_cast<std::uint64_t>(link.weight), 8);
    }
    if (payload.size() > max_payload) {
        throw std::invalid_argument("Binary snapshot payload exceeds 64 MiB");
    }
    std::vector<std::uint8_t> header(magic.begin(), magic.end());
    append(header, 1, 2);
    append(header, 0, 2);
    append(header, header_size, 4);
    append(header, data.fund_ids.size(), 4);
    append(header, data.security_ids.size(), 4);
    append(header, data.links.size(), 8);
    append(header, data.aliases.size(), 4);
    append(header, 0, 4);
    append(header, payload.size(), 8);
    append(header, checksum(payload), 8);
    append(header, 0, 8);
    output.write(reinterpret_cast<const char*>(header.data()), static_cast<std::streamsize>(header.size()));
    output.write(reinterpret_cast<const char*>(payload.data()), static_cast<std::streamsize>(payload.size()));
    if (!output) {
        throw std::runtime_error("Binary snapshot write failed");
    }
}

ExposureGraph read_binary_snapshot(std::istream& input) {
    std::array<std::uint8_t, header_size> header{};
    input.read(reinterpret_cast<char*>(header.data()), static_cast<std::streamsize>(header.size()));
    if (input.gcount() != static_cast<std::streamsize>(header.size())) {
        throw std::invalid_argument("Truncated binary snapshot header");
    }
    if (!std::equal(magic.begin(), magic.end(), header.begin())) {
        throw std::invalid_argument("Wrong binary snapshot magic");
    }
    Reader fields(std::span<const std::uint8_t>(header).subspan(8));
    if (fields.integer(2) != 1 || fields.integer(2) != 0 || fields.integer(4) != header_size) {
        throw std::invalid_argument("Unsupported binary snapshot version/flags/header size");
    }
    const auto funds = fields.integer(4), securities = fields.integer(4);
    const auto edges = fields.integer(8), aliases = fields.integer(4);
    if (fields.integer(4) != 0) {
        throw std::invalid_argument("Nonzero binary snapshot reserved field");
    }
    const auto length = fields.integer(8), expected_hash = fields.integer(8);
    if (fields.integer(8) != 0 || funds > max_nodes || securities > max_nodes ||
        edges > max_edges || aliases > max_edges || length > max_payload ||
        length < (securities + 1U) * 8U + edges * 16U + (funds + securities) * 5U + aliases * 9U) {
        throw std::invalid_argument("Impossible binary snapshot counts or size");
    }
    std::vector<std::uint8_t> payload(static_cast<std::size_t>(length));
    input.read(reinterpret_cast<char*>(payload.data()), static_cast<std::streamsize>(length));
    if (input.gcount() != static_cast<std::streamsize>(length) || input.peek() != std::char_traits<char>::eof()) {
        throw std::invalid_argument("Truncated snapshot payload or trailing bytes");
    }
    if (checksum(payload) != expected_hash) {
        throw std::invalid_argument("Binary snapshot integrity checksum failed");
    }
    Reader reader(payload);
    GraphSnapshotData data;
    data.fund_ids.reserve(static_cast<std::size_t>(funds));
    data.security_ids.reserve(static_cast<std::size_t>(securities));
    data.aliases.reserve(static_cast<std::size_t>(aliases));
    data.offsets.reserve(static_cast<std::size_t>(securities + 1U));
    data.links.reserve(static_cast<std::size_t>(edges));
    for (std::uint64_t index = 0; index < funds; ++index) { data.fund_ids.push_back(reader.string()); }
    for (std::uint64_t index = 0; index < securities; ++index) { data.security_ids.push_back(reader.string()); }
    for (std::uint64_t index = 0; index < aliases; ++index) {
        auto ticker = reader.string();
        const auto security = reader.integer(4);
        data.aliases.push_back({std::move(ticker), static_cast<std::size_t>(security)});
    }
    for (std::uint64_t index = 0; index <= securities; ++index) {
        const auto offset = reader.integer(8);
        if (offset > edges) {
            throw std::invalid_argument("Binary snapshot offset exceeds edge count");
        }
        data.offsets.push_back(static_cast<std::size_t>(offset));
    }
    for (std::uint64_t index = 0; index < edges; ++index) {
        const auto fund = reader.integer(4), present = reader.integer(1), reserved = reader.integer(3);
        const auto weight = std::bit_cast<double>(reader.integer(8));
        if (present > 1 || reserved != 0 || !std::isfinite(weight)) {
            throw std::invalid_argument("Invalid binary snapshot weight/flags");
        }
        data.links.push_back({static_cast<std::size_t>(fund), weight, present != 0});
    }
    if (!reader.exhausted()) {
        throw std::invalid_argument("Unconsumed binary snapshot bytes");
    }
    return ExposureGraph::from_snapshot(std::move(data));
}

} // namespace etf_genome
