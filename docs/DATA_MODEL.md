# Data model

Phase 1 stores denormalized holdings snapshots. A snapshot is one fund on one date. Identity fields are repeated on each row so a single Parquet file can be queried without a join. That repetition is deliberate for analytical reads. `FundMetadata` in SQLite is the small catalog copy of the fund attributes.

## Identifiers

| Field | Role |
| --- | --- |
| `fund_id` | Internal fund key. Caller-supplied, or `cik:{10 digits}\|series:{SERIES_ID}` when both parts exist. Never a ticker. |
| `ticker` | Fund ticker, display only. Uppercased. |
| `cik`, `series_id`, `class_id` | SEC-style identifiers when the source has them. |
| `security_id` | Internal holding key. Preference: `cusip:`, `isin:`, `ticker:`, then `name:`. |
| `security_ticker` | Constituent ticker. This is separate from the fund ticker. |
| `cusip`, `isin` | Stored when the source provides them. Missing values stay null. Invalid CUSIPs are not dropped in Phase 1; `cusip_is_valid` is available for later quality checks. |

A security that appears twice in one snapshot under the same `security_id` is one economic position. Quantities, market values, and weights are summed. If descriptive fields disagree, that field is stored as null and the normalization result carries a warning. Summing assumes the rows are lots of the same security. Exact duplicate filings would be double-counted; the warning is the signal to inspect them. Phase 1 does not silently discard the extra row.

## Canonical holdings columns

`etf_genome.data.normalization.holdings.CANONICAL_COLUMNS` is the contract:

`snapshot_date`, `fund_id`, `fund_name`, `ticker`, `cik`, `series_id`, `class_id`, `security_id`, `security_name`, `security_ticker`, `cusip`, `isin`, `asset_type`, `sector`, `industry`, `country`, `quantity`, `market_value`, `portfolio_weight`, `currency`, `source`, `source_timestamp`.

`security_ticker`, `cik`, `series_id`, and `class_id` are included in addition to a shorter field list so a fund ticker and a constituent ticker are not forced into one column, and so SEC identifiers are not discarded.

`portfolio_weight` is a fraction. `0.25` means 25 percent of the reported basis. Callers pass `weight_unit="percent"` when the source column is a percent. There is no automatic unit guess. A guess would rescale a real portfolio.

`market_value_scale` defaults to 1. N-PORT's `value` field is thousands of US dollars. `frame_from_nport_like` multiplies that field by 1000 and converts `pctVal` from a percent to a fraction. The normalizer itself does not special-case a column named `value`, because that name is ambiguous.

Null means the source did not provide the value. The pipeline does not fill missing ISINs, sectors, countries, or industries.

Weights are derived from market value only when, for an entire snapshot, every weight is null, every market value is present, and the market values do not sum to zero. The derived weight is `market_value / sum(market_value)`. A warning is recorded. If only some weights are missing, the missing ones stay null so reported weights and value weights are not mixed.

## Storage

| Store | Choice | Why |
| --- | --- | --- |
| Parquet | One file at `processed/holdings/{safe_fund_id}/{YYYY-MM-DD}.parquet` | Columnar snapshot storage. The desktop app can read it without a database server. Fund ids are encoded to a single Windows-safe directory name; the original `fund_id` remains inside the file and the SQLite catalog. |
| SQLite | `catalog.sqlite` | Fund metadata and the snapshot index. Small, transactional, local. |
| DuckDB | `analytics.duckdb` plus `read_parquet` | Aggregations over the Parquet files. Connections are opened per query and closed, so a Windows file lock does not outlive the call. If the DuckDB native library cannot be loaded, `LocalHoldingsStore.summarize` runs the same group-by in Polars and reports `polars_fallback`. |
| File cache | `cache/sec/{sha256}.body` | SEC response bodies with a TTL. The URL is not used as a path. |

Writes replace a snapshot file via a temporary file in the same directory. Reading a missing snapshot raises `SnapshotNotFound`.

## Concentration

Implemented in `etf_genome.features.concentration.metrics`.

Observed weights are the non-null `portfolio_weight` values.

Top-k concentration is the sum of the k largest observed weights. The weights are not divided by their total. A top-10 of `0.42` means 42 percent of the reported basis. If fewer than k weights exist, the available weights are summed. If none exist, the result is null. Null weights still count toward `holdings_count`.

HHI is `sum(s_i^2)`.

- Non-negative weights: `s_i = w_i / sum(w)` over observed weights. Renormalizing makes snapshots comparable when the reported weights do not add to 1. It does not invent the missing remainder. `hhi_method` is `renormalized_observed_weights`.
- Any negative weight: `s_i = |w_i| / sum(|w|)`. `hhi_method` is `gross_absolute_share`.
- Denominator zero: HHI is null. A portfolio of zeros does not get an invented index.

`weight_sum` is the sum of observed weights before renormalization. A sum far from 1 is reported through normalization warnings when it is above 1.5 or negative. The values are not rescaled.

Sector and country allocations sum `portfolio_weight` by label. A null label is reported as `UNCLASSIFIED`. That word means the source omitted the classification. It is not a predicted sector or country. Rows whose weights are all null keep a null allocation weight rather than a fabricated zero, except that a null-preserving sum of no values is null.

Largest positions are ordered by reported weight, descending, with `security_id` as a tie break. Null weights sort last.

## Mandate drift

Implemented in `etf_genome.features.drift`.

The report compares an earlier snapshot with a later snapshot of the same `fund_id`. The earlier date must be strictly before the later date.

### Holdings and sector distance

Vectors are aligned on the union of keys. A security or sector that is absent from one snapshot contributes weight 0 on that side. Zero means "not held" or "no weight in that label". A holding that is present but has a null weight is omitted from the distribution and mentioned in `notes`. It is not treated as zero, because zero would be a fabricated weight.

The default metric is Jensen-Shannon distance:

```text
p and q are scaled to sum to 1
m = 0.5 * (p + q)
JS = 0.5 * KL(p || m) + 0.5 * KL(q || m)
distance = sqrt(JS)
```

KL uses log base 2, and `0 * log(0)` is treated as 0. The distance is 0 when the compositions match and at most 1. It is a composition metric: it answers how the weight was redistributed among the observed names. It does not say whether the change is attractive.

Cosine distance (`1 - cosine similarity`, similarity clamped to [-1, 1]) is used only when a negative weight makes Jensen-Shannon undefined. The report names the metric in `overall_drift_metric`. `overall_drift` is that holdings distance. It is not a blend of sector drift and concentration drift, and it is not a buy or sell score.

Sector drift uses the same rule on sector weights, including the `UNCLASSIFIED` bucket when a sector is missing. If neither snapshot has a real sector classification, sector drift is unavailable. N-PORT does not provide GICS sectors, so the SEC path leaves `sector` null and does not infer one from the security name.

For an SEC filing, `snapshot_date` is `repPdDate`, the submissions `filingDate` is the publication date, and `downloaded_at` in the catalog is when ETF Genome stored the file.

### Concentration drift

Deltas are later minus earlier:

- `top_10_delta`
- `hhi_delta`
- `holdings_count_delta`

If either HHI is null, `hhi_delta` is null.

### Weight changes

For ranking increases and decreases, a security missing from one snapshot has weight 0 on that side. A null weight on a present security removes that security from the ranked lists and adds a note. Lists are ordered by the size of the move and then by `security_id`. The default list length is 5.

## Sample fixture

`tests/fixtures/sample_holdings.json` is a synthetic two-date book for `SAMPLE-SERIES-001` (ticker `SMPL`). Weights in the file are percents and are converted during normalization. Several identifiers are intentionally null. Do not describe this file as a download or as a real ETF.

## Look-ahead and leakage

Phase 1 does not train a predictor, so it does not split a sample. The snapshot date is still the only time key the features use. Later supervised work should train, validate, and test by time. It should not randomly shuffle dates, and it should not use a revised macro value that was unavailable on the snapshot date. FRED/ALFRED point-in-time handling is Phase 5 and is not implemented here.

## Domain objects

Pydantic models in `etf_genome.domain.models` mirror this layout: `ETF`, `Security`, `Holding`, `HoldingsSnapshot`, `FundMetadata`, `SectorExposure`, `CountryExposure`, `ConcentrationMetrics`, `DriftMetrics`, and `DriftReport`. The analytical path uses Polars frames. The service converts the calculated results into those models before they reach the desktop summary.
