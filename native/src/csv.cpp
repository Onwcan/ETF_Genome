#include "etf_genome/csv.hpp"

#include <charconv>
#include <cmath>
#include <iomanip>
#include <limits>
#include <stdexcept>
#include <unordered_set>

namespace etf_genome {
namespace {

using Row = std::vector<std::string>;

struct ReadBudget {
    std::size_t bytes = 0;
    std::size_t records = 0;

    int get(std::istream& input) {
        const auto value = input.get();
        if (value != std::char_traits<char>::eof() && ++bytes > 64U * 1024U * 1024U) {
            throw std::invalid_argument("CSV file exceeds the 64 MiB input limit");
        }
        return value;
    }
};

// Parse one logical record, allowing escaped quotes and newlines inside quoted fields.
bool read_row(std::istream& input, Row& row, ReadBudget& budget) {
    row.clear();
    std::string field;
    bool quoted = false;
    bool closed_quote = false;
    bool saw_character = false;
    const auto record_start = budget.bytes;
    for (;;) {
        if (field.size() > 4096 || budget.bytes - record_start > 16384 || row.size() > 4) {
            throw std::invalid_argument("CSV field or record exceeds the documented size limit");
        }
        const auto next = budget.get(input);
        if (budget.bytes - record_start > 16384) {
            throw std::invalid_argument("CSV record exceeds the 16384 byte size limit");
        }
        if (next == std::char_traits<char>::eof()) {
            if (input.bad()) {
                throw std::runtime_error("CSV read failed");
            }
            if (quoted) {
                throw std::invalid_argument("Unclosed quoted CSV field");
            }
            if (!saw_character) {
                return false;
            }
            if (++budget.records > 1000001) {
                throw std::invalid_argument("CSV exceeds the one million data row limit");
            }
            row.push_back(std::move(field));
            return true;
        }
        saw_character = true;
        const auto character = static_cast<char>(next);
        if (quoted) {
            if (character == '"') {
                if (input.peek() == '"') {
                    budget.get(input);
                    field.push_back('"');
                } else {
                    quoted = false;
                    closed_quote = true;
                }
            } else {
                field.push_back(character);
            }
            continue;
        }
        if (character == ',') {
            row.push_back(std::move(field));
            field.clear();
            closed_quote = false;
        } else if (character == '\n' || character == '\r') {
            if (character == '\r' && input.peek() == '\n') {
                budget.get(input);
            }
            if (budget.bytes - record_start > 16384) {
                throw std::invalid_argument("CSV record exceeds the 16384 byte size limit");
            }
            if (++budget.records > 1000001) {
                throw std::invalid_argument("CSV exceeds the one million data row limit");
            }
            row.push_back(std::move(field));
            return true;
        } else if (character == '"' && field.empty() && !closed_quote) {
            quoted = true;
        } else {
            if (closed_quote || character == '"') {
                throw std::invalid_argument("Invalid quoting in CSV field");
            }
            field.push_back(character);
        }
    }
}

void require_header(std::istream& input, const Row& expected, ReadBudget& budget) {
    // Strip the BOM before parsing so a quoted first header is also valid.
    if (input.peek() == 0xEF) {
        if (budget.get(input) != 0xEF || budget.get(input) != 0xBB || budget.get(input) != 0xBF) {
            throw std::invalid_argument("Invalid UTF-8 BOM in CSV header");
        }
    }
    Row header;
    if (!read_row(input, header, budget)) {
        throw std::invalid_argument("CSV file is empty");
    }
    if (header != expected) {
        throw std::invalid_argument("CSV header does not match the documented schema");
    }
}

double number(const std::string& text) {
    double value = 0.0;
    const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
    if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() || !std::isfinite(value)) {
        throw std::invalid_argument("CSV numbers must be finite decimal values without whitespace");
    }
    return value;
}

std::string quote(const std::string& value) {
    if (value.find_first_of(",\"\r\n") == std::string::npos) {
        return value;
    }
    std::string escaped = "\"";
    for (const auto character : value) {
        if (character == '"') {
            escaped += "\"\"";
        } else {
            escaped.push_back(character);
        }
    }
    escaped.push_back('"');
    return escaped;
}

} // namespace

std::vector<Holding> read_holdings_csv(std::istream& input) {
    ReadBudget budget;
    require_header(input, {"etf_node_id", "security_node_id", "security_ticker", "portfolio_weight"}, budget);
    std::vector<Holding> holdings;
    Row row;
    while (read_row(input, row, budget)) {
        if (row.size() != 4 || row[0].empty() || row[1].empty()) {
            throw std::invalid_argument("Every holdings row needs four columns and nonempty node ids");
        }
        holdings.push_back(Holding{std::move(row[0]), std::move(row[1]), std::move(row[2]),
                                   row[3].empty() ? std::nullopt
                                                  : std::optional<double>{number(row[3])}});
    }
    return holdings;
}

std::vector<std::pair<std::string, double>> read_shocks_csv(std::istream& input) {
    ReadBudget budget;
    require_header(input, {"key", "shock"}, budget);
    std::vector<std::pair<std::string, double>> shocks;
    std::unordered_set<std::string> keys;
    Row row;
    while (read_row(input, row, budget)) {
        if (row.size() != 2 || row[0].empty()) {
            throw std::invalid_argument("Every shocks row needs a nonempty key and a shock value");
        }
        if (!keys.insert(row[0]).second) {
            throw std::invalid_argument("Duplicate shock key; use one scenario value per key");
        }
        shocks.emplace_back(row[0], number(row[1]));
    }
    return shocks;
}

void write_impacts_csv(std::ostream& output, const ExposureGraph& graph,
                       const ExposureWorkspace& workspace) {
    if (graph.fund_ids().size() != workspace.impacts().size()) {
        throw std::invalid_argument("Workspace fund count does not match output graph");
    }
    output << "etf_node_id,direct_shock,covered_weight,weight_sum,missing_weight_count\n";
    output << std::setprecision(std::numeric_limits<double>::max_digits10);
    for (std::size_t index = 0; index < graph.fund_ids().size(); ++index) {
        const auto& impact = workspace.impacts()[index];
        output << quote(graph.fund_ids()[index]) << ',' << impact.direct_shock << ','
               << impact.covered_weight << ',' << impact.weight_sum << ','
               << impact.missing_weight_count << '\n';
    }
    if (!output) {
        throw std::runtime_error("CSV write failed");
    }
}

} // namespace etf_genome
