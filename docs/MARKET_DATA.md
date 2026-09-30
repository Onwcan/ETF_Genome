# Market data

The market-data layer stores daily QQQ bars and supplies the authoritative series for risk features, model training, and desktop inference. It does not place orders or produce buy/sell signals.

See [Free Data Providers](FREE_DATA_PROVIDERS.md) for provider roles and [Data Model](DATA_MODEL.md) for holdings semantics.

## Authoritative provider

The implemented provider is Twelve Data's public HTTPS `time_series` endpoint:

```text
GET https://api.twelvedata.com/time_series
interval=1day
adjust=all
```

The adapter requests split and dividend adjustment with `adjust=all` and parses one OHLC series (`open`, `high`, `low`, `close`, `volume`). It does not fetch a second raw series. ETF Genome stores those prices in `open` / `high` / `low` / `close`, leaves `adjusted_*` null, and records `adjustment_mode=all` plus `provider=twelvedata` on every bar. Features use `close` from that series only. Raw and adjusted values are never mixed.

The configured data path uses daily bars. Intraday bars, WebSockets, paid fundamentals, and paid ETF metrics are not requested. Missing fields stay null. Users must verify their current provider entitlement and usage terms; provider plans are not part of the repository's schema contract.

The API key is read from `ETF_GENOME_TWELVE_DATA_API_KEY`. It is not hard-coded, logged, or packaged. With no key the provider status is `NOT_CONFIGURED` and the app keeps using cached bars.

Downloaded bars live under the local data directory (`data\processed\market\` in a checkout). They are not copied into `ETFGenome.exe` or supplied as public source artifacts. Users configure their own permitted provider access.

## Provider boundary

`MarketDataProvider.fetch_daily_bars` returns canonical `MarketBar` rows. Feature code and XGBoost do not import Twelve Data. `MarketDataProviderRegistry` can construct Twelve Data, Tiingo, Alpha Vantage, Massive, and Yahoo Finance providers. Stooq is catalogued but disabled. Secondary providers support explicit comparison; they do not automatically replace the authoritative provider. A training series must come from one provider and one adjustment mode; the authoritative Parquet filename is `twelvedata_all.parquet`.

## Sync

The first sync starts at `market_history_start` (default `2019-01-01`). Its request end uses a 16:30 America/New_York cutoff; returned provider bars determine actual trading dates. The cutoff helper is not a full exchange holiday calendar. Later syncs start the day after the newest stored session. Upserts keep one row per trading date, and weekend rows are not invented.

The desktop's combined background worker checks both SEC and market data. Its periodic Qt timer uses `sec_update_interval_hours` (default 12); market requests also respect `market_update_interval_hours` (default 6). That separate eligibility gate does not create an independent six-hour timer. Startup and manual refresh use the same coordinator. See [Background Updates](BACKGROUND_UPDATES.md) for scheduling and failure behavior.

A rate-limit response backs off. A failed download does not delete stored bars. New bars can refresh inference from saved models; they do not start retraining.

## Point-in-time holdings

Genome features join on `available_from`, the SEC filing date. A portfolio report is not usable on dates before that filing was public. For example, a June 30 report filed on August 28 cannot supply features for August 27.

Mandatory paid data subscriptions: **NONE**. Downloaded provider history remains local and is not a distributable project artifact.
