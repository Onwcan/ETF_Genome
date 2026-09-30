# Local background updates

ETF Genome displays cached holdings and saved-model estimates before attempting network refreshes. Provider failures keep previously stored data available. The desktop uses its own coordinator; it does not install a Windows service or require Airflow.

See [Market Data](MARKET_DATA.md) for daily-bar provenance and [Model Lifecycle](MODEL_LIFECYCLE.md) for saved-model selection.

## While the application is open

The PySide6 window starts a `SyncWorker` on a `QThread`. Its normal path calls `UpdateCoordinator.sync_background`, which checks SEC filings, checks authoritative market bars, and then scores the cached risk models.

| Trigger or boundary | Implemented behavior |
| --- | --- |
| Startup | Paint cached QQQ holdings first, then queue a refresh when automatic updates are enabled and offline mode is off |
| Periodic | One `QTimer` uses `sec_update_interval_hours`, default 12 hours |
| Provider eligibility | SEC checks use the 12-hour default; market checks independently use `market_update_interval_hours`, default 6 hours |
| Manual | Refresh Now uses the same background worker with reason `manual` |
| Concurrent request | The window avoids a second active worker; the coordinator also has separate SEC and market locks |
| Shutdown | Request cancellation, wait up to three seconds for the worker thread, and close the SEC client |

The market interval is an eligibility check inside a background request, not a separate six-hour timer. A continuously open application therefore receives periodic requests on the configured desktop timer cadence.

Startup and periodic checks skip provider requests while a successful check is still inside that provider's interval. Manual refresh bypasses the ordinary interval but respects failure backoff. A 403, 429, or other provider error does not cause immediate repeated requests. Missing market configuration reports `NOT_CONFIGURED`; it does not switch to another provider.

Synchronization updates cached data and inference results. It does not retrain, tune, or promote models.

## Dates and freshness

These concepts remain separate:

| Concept | Field |
| --- | --- |
| Holdings portfolio date | N-PORT `repPdDate` / `snapshot_date` |
| SEC publication | Submissions `filingDate` / `available_from` |
| Local retrieval | `downloaded_at` |
| Provider check attempt | Sync state `last_attempt_at` |
| Successful provider check | Sync state `last_success_at` |
| Latest stored market session | Market bar `trading_date` |

`CURRENT` describes the provider check state. It does not mean a holdings report or market bar is dated today. Point-in-time graph and risk joins use filing availability, not the portfolio date alone; see [Data Model](DATA_MODEL.md) and [Graph Data Model](GRAPH_DATA_MODEL.md).

## While the application is closed

No installed Windows service or scheduled task performs updates after the desktop closes. A checkout can run the existing source synchronization scripts without opening the window:

```powershell
.\.venv\Scripts\python.exe scripts\sync_real_qqq.py
.\.venv\Scripts\python.exe scripts\sync_market_qqq.py
```

These commands require the respective provider configuration. The frozen executable normally opens the window. `ETF_GENOME_DESKTOP_SYNC_ONCE=1` is a diagnostic that opens it, runs one background request, and exits; it is not a silent scheduled-task mode. `ETF_GENOME_HEADLESS_SUMMARY=1` prints the cached summary without synchronization.

An optional installed scheduler and release integration remain in the [Windows release roadmap](ROADMAP.md#windows-release-preparation).

## Provider boundaries

The background path implements SEC NPORT-P ingestion for QQQ and Twelve Data daily-bar synchronization. Other market adapters are available for explicit comparison, without automatic failover; see [Free Data Providers](FREE_DATA_PROVIDERS.md).

`FredProvider` is only a point-in-time macro interface. No FRED/ALFRED ingestion runs in this coordinator. Credentials and SEC contact details come from local environment configuration, not from the executable or repository.
