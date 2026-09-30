# Shock graph

Phase 7 builds a point-in-time ETF-security graph from public N-PORT holdings. It does not predict prices and it does not learn how a shock spreads beyond the holdings that were named.

## Snapshot date

For graph date `t` and ETF `e`, the graph uses the latest stored filing with `available_from <= t`. `available_from` is the SEC filing date. A portfolio dated June 30 that was filed on August 28 is absent from a graph dated August 27.

## Nodes and edges

ETF nodes use `cik` plus `series_id`. The ticker is a label. Security nodes prefer CUSIP, then ISIN, then ticker, then a name fallback. Placeholder values such as `N/A` and `NONE` are not identifiers. Holdings that share a security id inside one filing are summed. Negative weights are kept.

The bipartite edge list is authoritative. The ETF-to-ETF table is a projection.

## Overlap

For two portfolios aligned on security id:

- Weighted overlap is `sum_i min(w_i_A, w_i_B)`. When every aligned weight is non-negative, that sum is a long-only overlap mass. If either book has a negative weight, the same number is still computed and `weighted_overlap_is_long_only` is false. It is not then described as a percentage of the portfolio.
- Cosine similarity uses the aligned weight vectors, with a missing holding treated as weight zero. It measures composition similarity, not future returns.
- Jaccard is `|intersection| / |union|` of the holdings sets. It ignores weights.

## Crowding

Security crowding counts how many ETFs in this universe hold the security, plus the sum, average, and maximum of reported weights. The denominator is the ETF count in the graph universe. It is not the share of all ETFs in the market.

Degree is the holdings count. Absolute weighted degree is the sum of absolute portfolio weights.

## Direct shock

```text
direct_shock = sum(portfolio_weight_i * shock_i)
covered_weight = sum(portfolio_weight_i)
```

over holdings whose security is in the scenario. Missing weights are excluded. A negative weight can reverse the contribution. `covered_weight` is only the slice of the book named by the scenario.

Learned secondary propagation is not implemented.

## Representation baseline

The optional PyTorch model learns ETF and security embeddings by reconstructing held links. The edge split is a hash of the pair. It is not the XGBoost time-series split. Embeddings are a structural description. They are not a forecast and they are not a recommendation.

## Scale

Per-fund N-PORT downloads are the Phase 7 path. The SEC also publishes quarterly bulk Form N-PORT data sets. Those files are large. They were not downloaded. They are the better source if this graph later covers hundreds of funds. The current parser remains the one that turns an NPORT-P document into holdings.

## Phase 11 research

Later work can stack these snapshots by publication date, add selected security market data, and compare a temporal model with this direct shock. That work is not in this phase.
