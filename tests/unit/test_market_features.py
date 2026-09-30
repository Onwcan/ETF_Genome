"""Local market features and forward risk labels."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from etf_genome.features.market.series import (
    FORWARD_HORIZON,
    MARKET_FEATURES,
    add_forward_targets,
    add_market_features,
    path_drawdown_magnitude,
)
from etf_genome.features.risk.dataset import TRAIN_END, VALIDATION_END, assign_temporal_split


def _frame(closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trading_date": [
                date(2020, 1, 1) + timedelta(days=index) for index in range(len(closes))
            ],
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1000.0 + index for index in range(len(closes))],
        }
    )


def test_returns_log_returns_and_momentum() -> None:
    frame = add_market_features(_frame([100.0, 110.0, 121.0]))
    assert frame.get_column("return_1d")[1] == pytest.approx(0.1)
    assert frame.get_column("log_return_1d")[1] == pytest.approx(math.log(1.1))
    assert frame.get_column("return_1d")[0] is None
    longer = add_market_features(_frame([100.0 + index for index in range(21)]))
    expected = longer.get_column("close")[20] / longer.get_column("close")[0] - 1
    assert longer.get_column("momentum_20d")[20] == pytest.approx(expected)
    assert longer.get_column("volume_zscore_20d")[19] is not None
    assert longer.get_column("rolling_max_drawdown_20d")[19] is not None


def test_realized_volatility_uses_trailing_sample_std() -> None:
    closes = [100.0 * math.exp(0.01 * index) for index in range(8)]
    frame = add_market_features(_frame(closes))
    logs = np.diff(np.log(np.array(closes[:6])))
    expected = float(np.std(logs, ddof=1) * math.sqrt(252))
    assert frame.get_column("realized_vol_5d")[5] == pytest.approx(expected)
    assert frame.get_column("realized_vol_5d")[4] is None


def test_drawdown_and_ranges() -> None:
    assert path_drawdown_magnitude(np.array([100.0, 110.0, 88.0])) == pytest.approx(
        (110 - 88) / 110
    )
    frame = add_market_features(_frame([100.0, 110.0, 88.0]))
    assert frame.get_column("rolling_drawdown")[2] == pytest.approx((110 - 88) / 110)
    assert frame.get_column("high_low_range")[0] == pytest.approx(0.02)
    assert frame.get_column("volume_change")[1] == pytest.approx(1001 / 1000 - 1)


def test_missing_sessions_are_not_synthesized() -> None:
    frame = _frame([100.0, 101.0, 102.0])
    skipped = frame.with_columns(
        pl.Series("trading_date", [date(2024, 1, 1), date(2024, 1, 3), date(2024, 1, 5)])
    )
    featured = add_market_features(skipped)
    assert featured.height == 3
    assert featured.get_column("trading_date").to_list()[1] == date(2024, 1, 3)


def test_forward_volatility_drawdown_and_label_end() -> None:
    returns = np.array([0.01, -0.02] * 12)
    closes = list(np.exp(np.cumsum(np.concatenate([[0.0], returns]))) * 100)
    featured = add_forward_targets(add_market_features(_frame(closes)), tail_threshold=0.08)
    expected_vol = float(np.std(returns[:FORWARD_HORIZON], ddof=1) * math.sqrt(252))
    path = np.array(closes[: FORWARD_HORIZON + 1])
    assert featured.get_column("forward_realized_vol_20d")[0] == pytest.approx(expected_vol)
    assert featured.get_column("forward_max_drawdown_20d")[0] == pytest.approx(
        path_drawdown_magnitude(path)
    )
    assert featured.get_column("label_end_date")[0] == featured.get_column("trading_date")[20]
    assert featured.get_column("forward_realized_vol_20d")[-1] is None
    assert "forward_realized_vol_20d" not in MARKET_FEATURES


def test_known_drawdown_magnitude_is_non_negative() -> None:
    path = [100.0, 110.0, 110.0, 110.0, 88.0] + [100.0] * 16
    featured = add_forward_targets(_frame(path), tail_threshold=0.08)
    assert featured.get_column("forward_max_drawdown_20d")[0] == pytest.approx((110 - 88) / 110)
    assert featured.get_column("tail_event_20d")[0] is True


def test_temporal_splits_purge_overlapping_labels() -> None:
    assert assign_temporal_split(date(2023, 12, 20), date(2024, 1, 19), 0.1) == "purged_train"
    assert assign_temporal_split(date(2023, 12, 1), date(2023, 12, 29), 0.1) == "train"
    assert assign_temporal_split(date(2024, 6, 3), date(2024, 7, 1), 0.1) == "validation"
    assert assign_temporal_split(date(2024, 12, 20), date(2025, 1, 17), 0.1) == "purged_validation"
    assert assign_temporal_split(date(2025, 1, 2), date(2025, 2, 3), 0.1) == "test"
    assert assign_temporal_split(date(2024, 6, 3), None, 0.1) == "no_target"
    assert assign_temporal_split(date(2024, 6, 3), date(2024, 7, 1), None) == "warmup"
    assert date(2023, 12, 31) == TRAIN_END
    assert date(2024, 12, 31) == VALIDATION_END
