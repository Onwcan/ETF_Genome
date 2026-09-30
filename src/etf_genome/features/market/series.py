"""Local market features from one adjusted close series.

Windows use only bars at or before the row date. ``rolling_std`` uses sample
standard deviation (ddof=1) and is annualized with sqrt(252).
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import polars as pl

FORWARD_HORIZON = 20
ANNUALIZATION = math.sqrt(252)


def add_market_features(bars: pl.DataFrame) -> pl.DataFrame:
    """Add trailing return, volatility, range, volume, and drawdown features."""

    frame = bars.sort("trading_date")
    close = pl.col("close")
    frame = frame.with_columns(
        (close / close.shift(1) - 1).alias("return_1d"),
        (close / close.shift(5) - 1).alias("return_5d"),
        (close / close.shift(20) - 1).alias("return_20d"),
        (close / close.shift(60) - 1).alias("return_60d"),
        (close.log() - close.shift(1).log()).alias("log_return_1d"),
        (close / close.shift(20) - 1).alias("momentum_20d"),
        (close / close.shift(60) - 1).alias("momentum_60d"),
        (close / close.shift(120) - 1).alias("momentum_120d"),
        ((pl.col("high") - pl.col("low")) / close).alias("high_low_range"),
        ((close - pl.col("open")) / pl.col("open")).alias("close_open_range"),
        (pl.col("volume") / pl.col("volume").shift(1) - 1).alias("volume_change"),
    )
    frame = frame.with_columns(
        (pl.col("log_return_1d").rolling_std(window_size=5, min_samples=5) * ANNUALIZATION).alias(
            "realized_vol_5d"
        ),
        (pl.col("log_return_1d").rolling_std(window_size=20, min_samples=20) * ANNUALIZATION).alias(
            "realized_vol_20d"
        ),
        (pl.col("log_return_1d").rolling_std(window_size=60, min_samples=60) * ANNUALIZATION).alias(
            "realized_vol_60d"
        ),
        _zscore("volume", 20).alias("volume_zscore_20d"),
        _zscore("volume", 60).alias("volume_zscore_60d"),
    )
    closes = np.array(frame.get_column("close").to_list(), dtype=np.float64)
    frame = frame.with_columns(
        pl.Series("rolling_drawdown", _trailing_drawdown(closes)),
        pl.Series("rolling_max_drawdown_20d", _rolling_drawdown(closes, 20)),
        pl.Series("rolling_max_drawdown_60d", _rolling_drawdown(closes, 60)),
    )
    return frame.with_columns(
        [
            pl.when(pl.col(name).is_finite()).then(pl.col(name)).otherwise(None).alias(name)
            for name in MARKET_FEATURES
            if name in frame.columns
        ]
    )


def add_forward_targets(frame: pl.DataFrame, *, tail_threshold: float) -> pl.DataFrame:
    """Add labels that use only future sessions. These columns are not features.

    ``forward_realized_vol_20d`` is ``sqrt(252) * std(log returns from t+1
    through t+20, ddof=1)``. The window is the next 20 stored sessions, not 20
    calendar days, and a missing session is not synthesized. The drawdown label
    is the non-negative peak-to-trough magnitude on closes ``t`` through
    ``t+20``. ``label_end_date`` is the trading date of session ``t+20``.
    ``tail_event_20d`` is true when that magnitude is at least ``tail_threshold``.
    """

    closes = np.array(frame.get_column("close").to_list(), dtype=np.float64)
    dates = frame.get_column("trading_date").to_list()
    vol: list[float | None] = [None] * len(closes)
    drawdown: list[float | None] = [None] * len(closes)
    label_ends: list[date | None] = [None] * len(closes)
    horizon = FORWARD_HORIZON
    for index in range(len(closes) - horizon):
        window = closes[index : index + horizon + 1]
        returns = np.diff(np.log(window))
        if returns.shape[0] != horizon or not np.isfinite(returns).all():
            continue
        vol[index] = float(np.std(returns, ddof=1) * ANNUALIZATION)
        drawdown[index] = path_drawdown_magnitude(window)
        end = dates[index + horizon]
        label_ends[index] = end if isinstance(end, date) else None
    out = frame.with_columns(
        pl.Series("forward_realized_vol_20d", vol, dtype=pl.Float64),
        pl.Series("forward_max_drawdown_20d", drawdown, dtype=pl.Float64),
        pl.Series("label_end_date", label_ends, dtype=pl.Date),
    )
    return out.with_columns(
        pl.when(pl.col("forward_max_drawdown_20d").is_not_null())
        .then(pl.col("forward_max_drawdown_20d") >= tail_threshold)
        .otherwise(None)
        .alias("tail_event_20d")
    )


def path_drawdown_magnitude(path: np.ndarray) -> float:
    """Maximum peak-to-trough decline on ``path``, as a non-negative fraction."""

    peak = float(path[0])
    worst = 0.0
    for price in path[1:]:
        value = float(price)
        if value > peak:
            peak = value
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def _rolling_drawdown(closes: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(closes), np.nan)
    for index in range(window - 1, len(closes)):
        out[index] = path_drawdown_magnitude(closes[index - window + 1 : index + 1])
    return out


def _trailing_drawdown(closes: np.ndarray) -> np.ndarray:
    out = np.full(len(closes), np.nan)
    peak = -math.inf
    for index, price in enumerate(closes):
        if not np.isfinite(price):
            continue
        peak = max(peak, float(price))
        out[index] = 0.0 if peak <= 0 else (peak - float(price)) / peak
    return out


def _zscore(column: str, window: int) -> pl.Expr:
    value = pl.col(column)
    mean = value.rolling_mean(window_size=window, min_samples=window)
    std = value.rolling_std(window_size=window, min_samples=window)
    return (value - mean) / std


MARKET_FEATURES = [
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "log_return_1d",
    "realized_vol_5d",
    "realized_vol_20d",
    "realized_vol_60d",
    "rolling_drawdown",
    "rolling_max_drawdown_20d",
    "rolling_max_drawdown_60d",
    "high_low_range",
    "close_open_range",
    "volume_change",
    "volume_zscore_20d",
    "volume_zscore_60d",
    "momentum_20d",
    "momentum_60d",
    "momentum_120d",
]

GENOME_FEATURES = [
    "holding_count",
    "reported_weight_sum",
    "top_1_weight",
    "top_5_concentration",
    "top_10_concentration",
    "hhi",
    "holdings_drift",
    "top_10_delta",
    "hhi_delta",
    "holding_count_delta",
    "days_since_holdings_report_date",
    "days_since_holdings_publication",
]
