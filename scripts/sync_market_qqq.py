"""Sync QQQ daily bars through the same service the desktop uses."""

from __future__ import annotations

import json
import sys

from etf_genome.config.settings import AppSettings
from etf_genome.data.ingestion.market_sync import sync_qqq_market
from etf_genome.logging_config import configure_logging


def main() -> int:
    settings = AppSettings()
    configure_logging(settings)
    result = sync_qqq_market(settings)
    print(
        json.dumps(
            {
                "symbol": result.symbol,
                "provider": result.provider,
                "status": result.status,
                "requested_start": result.requested_start,
                "requested_end": result.requested_end,
                "received_bars": result.received_bars,
                "new_bars": result.new_bars,
                "existing_bars": result.existing_bars,
                "latest_trading_date": result.latest_trading_date,
                "adjustment_mode": result.adjustment_mode,
                "storage_path": result.storage_path,
                "message": result.message,
            },
            indent=2,
        )
    )
    if result.status not in {"ok", "current"}:
        print(result.message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
