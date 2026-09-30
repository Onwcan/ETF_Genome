"""Compare two canonical QQQ series without merging them.

Twelve Data stores its adjusted history in ``close``. Tiingo and Yahoo store
the split/dividend-adjusted close in ``adjusted_close`` and the raw close in
``close``. The comparison uses that documented continuity price. It does not
copy rows from one provider into the other's file.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl


def continuity_close(frame: pl.DataFrame) -> pl.Expr:
    """Price used to compare adjustment-aware history."""

    if "adjusted_close" in frame.columns:
        return (
            pl.when(pl.col("adjusted_close").is_not_null())
            .then(pl.col("adjusted_close"))
            .otherwise(pl.col("close"))
        )
    return pl.col("close")


def compare_sessions(
    left: pl.DataFrame,
    right: pl.DataFrame,
    *,
    left_name: str,
    right_name: str,
) -> dict[str, object]:
    """Summarize overlapping sessions. Relative difference uses the left price."""

    left_view = _view(left, left_name)
    right_view = _view(right, right_name)
    joined = left_view.join(right_view, on="trading_date", how="full", coalesce=True)
    both = joined.filter(
        pl.col(f"{left_name}_close").is_not_null() & pl.col(f"{right_name}_close").is_not_null()
    )
    only_left = int(joined.filter(pl.col(f"{right_name}_close").is_null()).height)
    only_right = int(joined.filter(pl.col(f"{left_name}_close").is_null()).height)
    if both.is_empty():
        return {
            "left": left_name,
            "right": right_name,
            "overlap_start": None,
            "overlap_end": None,
            "common_sessions": 0,
            "missing_on_right": only_left,
            "missing_on_left": only_right,
            "close": {},
            "volume": {},
        }
    compared = both.with_columns(
        (pl.col(f"{left_name}_close") - pl.col(f"{right_name}_close")).abs().alias("close_abs"),
        (
            (pl.col(f"{left_name}_close") - pl.col(f"{right_name}_close")).abs()
            / pl.col(f"{left_name}_close")
        ).alias("close_rel"),
        (pl.col(f"{left_name}_volume") - pl.col(f"{right_name}_volume")).abs().alias("volume_abs"),
    )
    dates = compared.get_column("trading_date")
    return {
        "left": left_name,
        "right": right_name,
        "left_adjustment": _mode(left),
        "right_adjustment": _mode(right),
        "overlap_start": str(dates.min()),
        "overlap_end": str(dates.max()),
        "common_sessions": compared.height,
        "missing_on_right": only_left,
        "missing_on_left": only_right,
        "close": _stats(compared, "close_abs", "close_rel"),
        "volume": {
            "median_absolute_difference": _median(compared, "volume_abs"),
            "max_absolute_difference": _max(compared, "volume_abs"),
        },
    }


def write_comparison_report(payload: dict[str, object], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    stamped = {**payload, "created_at": datetime.now(UTC).isoformat()}
    (directory / "qqq_market_providers.json").write_text(
        json.dumps(stamped, indent=2),
        encoding="utf-8",
    )
    (directory / "qqq_market_providers.md").write_text(_markdown(stamped), encoding="utf-8")


def _view(frame: pl.DataFrame, name: str) -> pl.DataFrame:
    priced = frame.with_columns(continuity_close(frame).alias("_continuity"))
    return priced.select(
        [
            pl.col("trading_date"),
            pl.col("_continuity").alias(f"{name}_close"),
            (
                pl.col("volume").alias(f"{name}_volume")
                if "volume" in frame.columns
                else pl.lit(None).alias(f"{name}_volume")
            ),
        ]
    )


def _mode(frame: pl.DataFrame) -> str | None:
    if "adjustment_mode" not in frame.columns or frame.is_empty():
        return None
    values = frame.get_column("adjustment_mode").drop_nulls().unique().to_list()
    return None if not values else str(values[0])


def _stats(frame: pl.DataFrame, absolute: str, relative: str) -> dict[str, float | None]:
    return {
        "median_absolute_difference": _median(frame, absolute),
        "max_absolute_difference": _max(frame, absolute),
        "median_relative_difference": _median(frame, relative),
        "max_relative_difference": _max(frame, relative),
    }


def _median(frame: pl.DataFrame, column: str) -> float | None:
    return _number(frame.get_column(column).drop_nulls().median())


def _max(frame: pl.DataFrame, column: str) -> float | None:
    return _number(frame.get_column(column).drop_nulls().max())


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise TypeError("Comparison statistic is not numeric.")


def _markdown(payload: dict[str, object]) -> str:
    lines = [
        "# QQQ market provider comparison",
        "",
        "Prices are not merged. Each series keeps its own provider and adjustment mode.",
        "A relative difference is measured against the left series.",
        "Vendors are not expected to match to the cent.",
        "",
        f"Created: {payload.get('created_at', '')}",
        "",
    ]
    comparisons = payload.get("comparisons")
    if isinstance(comparisons, list):
        for item in comparisons:
            if not isinstance(item, dict):
                continue
            lines.append(f"## {item.get('left')} vs {item.get('right')}")
            lines.append("")
            left_mode = item.get("left_adjustment")
            right_mode = item.get("right_adjustment")
            lines.append(f"Adjustments: {left_mode} vs {right_mode}")
            lines.append(f"Overlap: {item.get('overlap_start')} through {item.get('overlap_end')}")
            lines.append(f"Common sessions: {item.get('common_sessions')}")
            lines.append(
                f"Missing on right: {item.get('missing_on_right')}; "
                f"missing on left: {item.get('missing_on_left')}"
            )
            lines.append("")
    lines.append("No provider is ranked as better. Differences can come from adjustment method,")
    lines.append("session calendars, or volume conventions.")
    return "\n".join(lines)
