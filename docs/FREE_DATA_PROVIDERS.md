# Free market-data providers

The provider catalog defines project roles and supported parsing paths. It is not a guarantee of a provider's current free-plan quota, historical coverage, or redistribution license. Verify current provider terms and account entitlements before downloading or sharing data.

The authoritative training and inference series remains Twelve Data's local `twelvedata_all.parquet` file. Explicit comparisons use separate provider data; automatic failover and mixed-provider training are not implemented. See [Market Data](MARKET_DATA.md) for storage and adjustment rules.

## Implemented provider roles

| Provider | Project classification | Implemented data path | Role |
| --- | --- | --- | --- |
| Twelve Data | `PRIMARY_FREE` | Daily `time_series` with `adjust=all`; one OHLC series | Authoritative QQQ feature, training, and inference input |
| Tiingo | `SECONDARY_FREE` | End-of-day bars with separate raw and adjusted OHLC fields | Optional comparison |
| Massive | `SECONDARY_FREE` | Daily aggregates requested with `adjusted=true`; split adjustment is not dividend total return | Optional comparison |
| Alpha Vantage | `FALLBACK_FREE` | `TIME_SERIES_DAILY`; unadjusted OHLC | Optional unadjusted comparison, excluded from the risk-model series |
| Yahoo Finance | `UNOFFICIAL_FALLBACK` | Public chart responses with raw OHLC and a separate `adjclose` field | Optional comparison through an unofficial endpoint |
| Stooq | `UNSUITABLE` | Catalogued; registry construction is disabled | No enabled download path |

These classifications are the names used in `data.sources.capabilities`. A secondary or fallback classification does not activate automatic substitution. Yahoo Finance uses the chart endpoint directly; the project does not depend on `yfinance`.

## Configuration

| Provider | Environment variable |
| --- | --- |
| Twelve Data | `ETF_GENOME_TWELVE_DATA_API_KEY` |
| Tiingo | `ETF_GENOME_TIINGO_API_KEY` |
| Massive | `ETF_GENOME_MASSIVE_API_KEY` |
| Alpha Vantage | `ETF_GENOME_ALPHA_VANTAGE_API_KEY` |
| Yahoo Finance | No key used by the implemented endpoint |
| Stooq | No enabled provider |

Missing keys produce a not-configured status. Credentials are supplied locally and must not appear in source, model metadata, logs, or packaged artifacts.

## Usage boundaries

Provider responses can differ in adjustment semantics, available fields, licensing, and history. Missing values remain missing. A successful endpoint response does not establish redistribution rights or training suitability.

The supplied comparison command fetches Yahoo Finance separately and compares it with the stored authoritative Twelve Data history:

```powershell
.\.venv\Scripts\python.exe scripts\compare_market_providers.py
```

It requires the authoritative local history, stores Yahoo bars in a separate provider file, and writes reports under `reports/provider_comparison`. It does not merge either series into the other or exercise all catalogued adapters. Inspect the returned status rather than treating a catalog entry as a live availability guarantee.

Downloaded market history stays local and is not bundled in the public source checkout or Windows executable. The project does not call Alpha Vantage's premium adjusted-daily endpoint or require a longer-history paid tier.

Mandatory paid data subscriptions: **NONE**.

See [Project Status](PROJECT_STATUS.md) for verified implementation boundaries and [Background Updates](BACKGROUND_UPDATES.md) for desktop request scheduling.
