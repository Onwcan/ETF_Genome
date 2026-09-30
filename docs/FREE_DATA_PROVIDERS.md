# Free market-data providers

Checked on 2026-09-22. Provider terms change. Re-check them before relying on a tier that is not listed here.

The training series remains the local Twelve Data file `twelvedata_all.parquet`. Other providers are optional and are not copied into that file.

## Twelve Data

```text
provider: Twelve Data
status: PRIMARY_FREE
authentication: ETF_GENOME_TWELVE_DATA_API_KEY
historical coverage: Basic free daily history, used here from 2019-01-02
rate limits: plan-specific; 429 is backed off and not brute-forced
adjustment support: adjust=all, one OHLC series stored in close
ETF support: yes, QQQ
license/use limitations: the key is bring-your-own; downloaded history stays local and is not bundled in the executable
role: authoritative daily series for features, training, and desktop inference
```

## Tiingo

```text
provider: Tiingo
status: SECONDARY_FREE
authentication: ETF_GENOME_TIINGO_API_KEY
historical coverage: Starter plan lists 30+ years of end-of-day prices
rate limits: Starter lists 50 requests/hour, 1,000/day, 500 unique symbols/month, 1 GB/month
adjustment support: separate raw OHLC and adjOpen/adjHigh/adjLow/adjClose
ETF support: yes
license/use limitations: Starter is internal use; redistribution is not assumed
role: optional comparison provider, not the training file
```

## Massive

```text
provider: Massive (formerly Polygon.io)
status: SECONDARY_FREE
authentication: ETF_GENOME_MASSIVE_API_KEY
historical coverage: Stocks Basic lists about two years of end-of-day history
rate limits: Stocks Basic lists 5 API calls per minute
adjustment support: aggregates adjusted=true is split adjustment, not dividend total return
ETF support: US stock tickers, including ETFs on that plan
license/use limitations: free tier is not used for the 2019 training window
role: recent-history comparison only
```

## Alpha Vantage

```text
provider: Alpha Vantage
status: FALLBACK_FREE
authentication: ETF_GENOME_ALPHA_VANTAGE_API_KEY
historical coverage: free TIME_SERIES_DAILY full output is multi-year unadjusted OHLC
rate limits: free key is about 25 requests per day
adjustment support: TIME_SERIES_DAILY_ADJUSTED is premium and is not called
ETF support: the stock time-series endpoints cover ETFs
license/use limitations: adjusted history would require a paid endpoint, so it is unused
role: unadjusted fallback only, unsuitable for the risk-model series
```

## Yahoo Finance

```text
provider: Yahoo Finance chart endpoint
status: UNOFFICIAL_FALLBACK
authentication: none
historical coverage: a QQQ daily request returned history and a separate adjclose field
rate limits: unpublished; failures are cached around rather than retried aggressively
adjustment support: raw OHLC plus adjclose
ETF support: QQQ responded on 2026-09-22
license/use limitations: not an official API and not the yfinance package; not a training source
role: optional overlap check against the Twelve Data file
```

## Stooq

```text
provider: Stooq
status: UNSUITABLE
authentication: an on-site CAPTCHA key was required for programmatic downloads as of early 2026
historical coverage: not verified for this app
rate limits: a daily quota exists; the exact number is not published
adjustment support: not documented as split-and-dividend adjustment
ETF support: US ETF files exist on the site
license/use limitations: redistribution of site data is not allowed without consent
role: catalogued and not enabled
```

## Paid subscriptions

No core path requires a paid market-data plan. Paid endpoints that were identified, including Alpha Vantage adjusted daily history and Massive's longer history tiers, are not called.
