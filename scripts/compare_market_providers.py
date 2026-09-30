"""Compare the stored Twelve Data series with the unofficial Yahoo chart.

The Yahoo file is separate. It is not copied into the training parquet.
"""

from __future__ import annotations

import json
import sys

from etf_genome.config.paths import project_root
from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.comparison import compare_sessions, write_comparison_report
from etf_genome.data.sources.market import QQQ_INSTRUMENT
from etf_genome.data.sources.yahoo import YahooFinanceProvider
from etf_genome.data.storage.market_store import MarketStore
from etf_genome.logging_config import configure_logging


def main() -> int:
    settings = AppSettings()
    configure_logging(settings)
    left = MarketStore(settings).read()
    if left.is_empty():
        print("No Twelve Data history is stored.", file=sys.stderr)
        return 1
    start = left.get_column("trading_date").min()
    end = left.get_column("trading_date").max()
    yahoo = YahooFinanceProvider(timeout=60)
    result = yahoo.fetch_daily_bars(QQQ_INSTRUMENT, start, end)
    if result.status != "ok" or not result.bars:
        print(result.message, file=sys.stderr)
        return 1
    store = MarketStore(
        settings,
        provider="yahoo",
        adjustment_mode=result.adjustment_mode or "raw_ohlc_plus_adjclose",
    )
    store.upsert(result.bars)
    payload = {
        "authoritative_provider": "twelvedata",
        "authoritative_file": "twelvedata_all.parquet",
        "note": (
            "Twelve Data continuity price is close because adjust=all. "
            "Yahoo continuity price is adjusted_close. The files are not merged."
        ),
        "comparisons": [
            compare_sessions(left, store.read(), left_name="twelvedata", right_name="yahoo")
        ],
    }
    write_comparison_report(payload, project_root() / "reports" / "provider_comparison")
    print(
        json.dumps(
            {
                "status": "ok",
                "yahoo_bars": len(result.bars),
                "report": "reports/provider_comparison",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
