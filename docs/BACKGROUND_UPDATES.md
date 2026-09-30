# Local background updates

ETF Genome is offline-first. The desktop process keeps previously stored holdings when the network fails. It does not install a Windows service, and it does not require Airflow.

## While the application is open

`UpdateCoordinator` is the only place that decides whether a provider may run. The PySide6 window starts that coordinator on a `QThread`.

- Startup: the window paints cached QQQ holdings first. A queued timer then asks for a startup sync.
- Periodic: a `QTimer` uses `sec_update_interval_hours` (default 12). It does not poll every few seconds. N-PORT holdings are quarterly, so checking more often would not make the portfolio fresher.
- Manual: the Refresh Now button calls the same `sync_sec("manual")` path.
- One flight: a second request while a sync holds the lock is ignored.
- Shutdown: close cancels the coordinator and waits up to three seconds for the worker thread.

If the last successful check is still inside the interval, startup and periodic runs do not contact the SEC. A manual refresh still respects failure backoff so a 403 or 429 is not retried immediately.

## Dates

These are stored separately:

| Concept | Field |
| --- | --- |
| Portfolio as-of | N-PORT `repPdDate` / `snapshot_date` |
| SEC publication | submissions `filingDate` |
| Retrieved by ETF Genome | `downloaded_at` |
| Last check | sync state `last_attempt_at` |

`CURRENT` means the provider was checked inside its interval and that check did not fail. It does not mean the holdings report is from today.

## While the application is closed

Phase 2 does not register a scheduled task. A later optional installer can add a Windows Task Scheduler entry that launches `ETFGenome.exe` with a headless sync flag, then exits. That task must not require a separate Python install, Docker, or Airflow. Register it only after the user opts in.

The headless command available from a checkout is:

```powershell
.\.venv\Scripts\python.exe scripts\sync_real_qqq.py
```

The frozen executable currently opens the window. A dedicated silent sync mode for Task Scheduler is deferred until the user-facing opt-in exists.

## Provider boundaries

Only SEC NPORT-P for QQQ is implemented. `MarketDataProvider` can later supply prices. `FredProvider` can later supply point-in-time macro series using `ETF_GENOME_FRED_API_KEY`. Neither provider is called in Phase 2, and no API key is embedded.
