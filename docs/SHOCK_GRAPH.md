# ETF-security shock graph

The graph layer builds a static point-in-time ETF-security graph from public N-PORT holdings. It implements overlap, crowding, and deterministic direct shock calculations. It does not model causal contagion or predict how a shock spreads beyond named holdings.

See [Graph Data Model](GRAPH_DATA_MODEL.md) for the artifact schema and [Architecture](ARCHITECTURE.md) for the Python/native responsibility boundary.

## Snapshot selection

For graph date `t` and ETF `e`, the graph selects the latest stored filing with `available_from <= t`. `available_from` is the SEC filing date. A portfolio dated June 30 that was filed on August 28 is absent from a graph dated August 27.

ETF nodes use CIK plus series ID; the ticker is a label. Security nodes prefer CUSIP, then ISIN, then ticker, then a normalized-name fallback. Placeholder values such as `N/A` and `NONE` are not identifiers. Holdings sharing a security ID inside one filing are summed, and negative weights are kept.

The bipartite edge list is authoritative. The ETF-to-ETF table is a projection.

## Overlap

For two portfolios aligned on security ID:

- Weighted overlap is `sum_i min(w_i_A, w_i_B)`. With non-negative weights, it is long-only overlap mass. If either portfolio has a negative weight, the number is still computed and `weighted_overlap_is_long_only` is false; it is not interpreted as a portfolio percentage.
- Cosine similarity uses aligned weight vectors, with an absent holding treated as zero. It measures composition similarity, not future returns.
- Jaccard is `|intersection| / |union|` of the holdings sets and ignores weights.

## Crowding

Security crowding counts ETFs holding a security and summarizes reported weights. Its denominator is the resolved ETF universe count used by the build, including resolved funds without an eligible filing. It is not the share of all ETFs in the market.

ETF degree counts holdings edges. Absolute weighted degree sums absolute portfolio weights.

## Direct shock

```text
direct_shock = sum(portfolio_weight_i * shock_i)
covered_weight = sum(portfolio_weight_i)
```

The sums include holdings named in the scenario. The scenario evaluator excludes missing edge weights and reports missing-weight coverage. A negative weight can reverse a contribution. `covered_weight` describes the named slice of the portfolio, without rescaling it to one.

Coverage is measured on the aggregated graph edges; [Graph Data Model](GRAPH_DATA_MODEL.md) documents the current all-null aggregation limitation. A shock result does not establish complete source-weight coverage.

The Python exporter writes selected graph edges and shocks to an explicit CSV contract for the native exposure engine. The native CLI can convert edge CSV to its binary snapshot format. See [Native Developer Guide](../native/README.md) and [Binary Protocol](BINARY_PROTOCOL.md).

## Representation research

An optional experimental PyTorch baseline exists in `research/graph/baseline.py`. Its intended task is held-link reconstruction using ETF/security embeddings and a deterministic hash-based edge split. That structural split is separate from the chronological XGBoost risk split.

Native Windows PyTorch execution was blocked by Application Control in the observed development environment. Successful graph-model training is not established by the presence of the baseline or its training script. See [Graph Research Environment](GRAPH_RESEARCH_ENVIRONMENT.md) for the isolated Linux/WSL setup.

Validated learned embeddings, temporal models, and secondary propagation remain research workstreams in the [Roadmap](ROADMAP.md#temporal-shock-graph-research). They are not current analytical outputs or investment recommendations.

## Data acquisition boundary

The implemented graph ingestion path uses per-fund NPORT-P discovery, download, and XML parsing. Bulk N-PORT ingestion is not implemented. Scaling and temporal graph plans belong in the [Roadmap](ROADMAP.md#temporal-shock-graph-research).
