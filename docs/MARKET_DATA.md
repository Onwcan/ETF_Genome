# Market data

Phase 4 stores one daily QQQ series and builds risk features from that series. It does not predict whether the price will rise or fall, and it does not place orders.

## Twelve Data Basic, free tier

The implemented provider is Twelve Data's public HTTPS `time_series` endpoint:

```text
GET https://api.twelvedata.com/time_series
interval=1day
adjust=all
```

`adjust=all` asks for a history adjusted for splits and dividends. The free response contains one OHLC series (`open`, `high`, `low`, `close`, `volume`). It does not include a second raw series. ETF Genome stores those prices in `open` / `high` / `low` / `close`, leaves `adjusted_*` null, and records `adjustment_mode=all` plus `provider=twelvedata` on every bar. Features use `close` from that series only. Raw and adjusted values are never mixed.

This uses the Basic free plan. Intraday bars, WebSockets, paid fundamentals, and paid ETF metrics are not requested. If a field is not in the free response, it stays null.

The API key is read from `ETF_GENOME_TWELVE_DATA_API_KEY`. It is not hard-coded, logged, or packaged. With no key the provider status is `NOT_CONFIGURED` and the app keeps using cached bars.

Downloaded bars live under the local data directory (`data\processed\market\` in a checkout). They are not copied into `ETFGenome.exe`. A later distribution must not ship this history. Other users bring their own permitted key or another free provider.

## Provider boundary

`MarketDataProvider.fetch_daily_bars` returns canonical `MarketBar` rows. Feature code and XGBoost do not import Twelve Data. `MarketDataProviderRegistry` lists Twelve Data as implemented and Tiingo, Alpha Vantage, Massive, Yahoo Finance, and Stooq as future names. Failover is not implemented. A training series must come from one provider and one adjustment mode; the Parquet path is `twelvedata_all.parquet`.

## Sync

The first sync requests `2019-01-01` through the latest completed US cash session (16:30 America/New_York). Later syncs start the day after the newest stored session. Upserts keep one row per trading date. Weekend rows are not invented. The desktop checks prices on `market_update_interval_hours` (default 6), which is separate from the 12-hour SEC check. A rate-limit response backs off. A failed download does not delete stored bars. The desktop never retrains the model when a new bar arrives.

## Point-in-time holdings

Genome features join on `available_from`, the SEC filing date. A portfolio report is not usable on dates before that filing was public. The June 30, 2026 QQQ report filed on August 28, 2026 is not used on August 27, 2026.
