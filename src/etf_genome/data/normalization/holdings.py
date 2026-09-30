"""Normalize source holdings into one canonical Polars frame.

Missing source fields stay null. This module does not invent identifiers,
sectors, countries, or weights. The only derived fields are:

* ``security_id`` and, when needed, ``fund_id``
* ``portfolio_weight`` when the entire snapshot has market values and no weights

Duplicate rows that share a snapshot and ``security_id`` are summed. If their
descriptive fields disagree, that field is stored as null and a warning is
recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import polars as pl

from etf_genome.errors import EtfGenomeError

WeightUnit = Literal["fraction", "percent"]

CANONICAL_COLUMNS: list[str] = [
    "snapshot_date",
    "fund_id",
    "fund_name",
    "ticker",
    "cik",
    "series_id",
    "class_id",
    "security_id",
    "security_name",
    "security_ticker",
    "cusip",
    "isin",
    "asset_type",
    "sector",
    "industry",
    "country",
    "quantity",
    "market_value",
    "portfolio_weight",
    "currency",
    "source",
    "source_timestamp",
]

_TEXT_COLUMNS: tuple[str, ...] = (
    "fund_id",
    "fund_name",
    "ticker",
    "cik",
    "series_id",
    "class_id",
    "security_name",
    "security_ticker",
    "cusip",
    "isin",
    "asset_type",
    "sector",
    "industry",
    "country",
    "currency",
    "source",
)

_CONFLICT_COLUMNS: tuple[str, ...] = (
    "fund_name",
    "ticker",
    "cik",
    "series_id",
    "class_id",
    "security_name",
    "security_ticker",
    "cusip",
    "isin",
    "asset_type",
    "sector",
    "industry",
    "country",
    "currency",
    "source",
)

_ALIASES: dict[str, str] = {
    "report_date": "snapshot_date",
    "period_of_report": "snapshot_date",
    "series_name": "fund_name",
    "name_of_issuer": "security_name",
    "holding_ticker": "security_ticker",
    "pct_val": "portfolio_weight",
    "pctval": "portfolio_weight",
    "balance": "quantity",
    "market_value_usd": "market_value",
    "asset_cat": "asset_type",
    "inv_country": "country",
    "issuer_country": "country",
}

_GROUP_KEYS = ["snapshot_date", "fund_id", "security_id"]
_DATETIME = pl.Datetime(time_unit="us", time_zone="UTC")


class NormalizationError(EtfGenomeError):
    """Raised when a holdings table cannot be normalized honestly."""


@dataclass(frozen=True)
class NormalizationResult:
    """Canonical frame plus data-quality warnings."""

    frame: pl.DataFrame
    warnings: list[str] = field(default_factory=list)
    rows_in: int = 0
    rows_out: int = 0
    duplicate_rows_merged: int = 0


def normalize_holdings(
    raw: pl.DataFrame,
    *,
    weight_unit: WeightUnit = "fraction",
    market_value_scale: float = 1.0,
) -> NormalizationResult:
    """Return a canonical holdings frame.

    ``weight_unit="percent"`` divides ``portfolio_weight`` by 100.
    ``market_value_scale`` multiplies ``market_value``. N-PORT US dollar
    values reported in thousands must be scaled by the caller (use 1000).
    There is no automatic unit guess, because a guess can silently rescale a
    real portfolio.
    """

    if raw.is_empty():
        raise NormalizationError("Cannot normalize an empty holdings table")
    if market_value_scale <= 0:
        raise NormalizationError("market_value_scale must be greater than zero")
    if weight_unit not in {"fraction", "percent"}:
        raise NormalizationError("weight_unit must be 'fraction' or 'percent'")

    warnings: list[str] = []
    frame = _apply_aliases(raw, warnings)
    frame = _ensure_text_columns(frame)
    frame = _coerce_dates(frame)
    frame = _coerce_measures(frame, market_value_scale, weight_unit)
    frame = _with_identifiers(frame)
    _reject_unidentified_rows(frame)

    duplicate_rows_merged = _duplicate_row_count(frame)
    if duplicate_rows_merged:
        warnings.append(
            f"Merged {duplicate_rows_merged} duplicate holding rows that share a security_id. "
            "Quantities, market values, and weights were summed."
        )
    warnings.extend(_conflict_warnings(frame))

    aggregated = _aggregate(frame)
    aggregated, derived = _derive_missing_weights(aggregated)
    warnings.extend(derived)
    warnings.extend(_weight_sum_warnings(aggregated))

    canonical = _finalize_schema(aggregated)
    return NormalizationResult(
        frame=canonical,
        warnings=warnings,
        rows_in=raw.height,
        rows_out=canonical.height,
        duplicate_rows_merged=duplicate_rows_merged,
    )


def concatenate_results(results: list[NormalizationResult]) -> NormalizationResult:
    """Stack normalized snapshots into one frame."""

    if not results:
        raise NormalizationError("No normalization results to combine")
    frame = pl.concat([result.frame for result in results], how="vertical_relaxed")
    frame = frame.sort(["fund_id", "snapshot_date", "security_id"])
    return NormalizationResult(
        frame=frame,
        warnings=[warning for result in results for warning in result.warnings],
        rows_in=sum(result.rows_in for result in results),
        rows_out=frame.height,
        duplicate_rows_merged=sum(result.duplicate_rows_merged for result in results),
    )


def _apply_aliases(frame: pl.DataFrame, warnings: list[str]) -> pl.DataFrame:
    for alias, target in _ALIASES.items():
        if alias not in frame.columns:
            continue
        if target in frame.columns:
            warnings.append(f"Ignored column {alias} because {target} is already present")
            frame = frame.drop(alias)
        else:
            frame = frame.rename({alias: target})
    return frame


def _blank_to_null(column: str) -> pl.Expr:
    text = pl.col(column).cast(pl.Utf8).str.strip_chars()
    return pl.when(text.is_null() | (text == "")).then(None).otherwise(text).alias(column)


def _ensure_text_columns(frame: pl.DataFrame) -> pl.DataFrame:
    for column in _TEXT_COLUMNS:
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
        else:
            frame = frame.with_columns(_blank_to_null(column))
    if "source_timestamp" not in frame.columns:
        frame = frame.with_columns(pl.lit(None, dtype=_DATETIME).alias("source_timestamp"))
    return frame


def _coerce_dates(frame: pl.DataFrame) -> pl.DataFrame:
    if "snapshot_date" not in frame.columns:
        raise NormalizationError("Holdings table is missing snapshot_date")
    dtype = frame.schema["snapshot_date"]
    if dtype == pl.Date:
        dated = frame
    elif dtype == pl.Null:
        raise NormalizationError("snapshot_date is null for every row")
    else:
        try:
            dated = frame.with_columns(
                pl.col("snapshot_date").cast(pl.Utf8).str.to_date(strict=True)
            )
        except pl.exceptions.PolarsError as exc:
            raise NormalizationError("snapshot_date contains a value that is not a date") from exc

    timestamp_dtype = dated.schema["source_timestamp"]
    if timestamp_dtype == pl.Null:
        dated = dated.with_columns(pl.lit(None, dtype=_DATETIME).alias("source_timestamp"))
    elif timestamp_dtype != _DATETIME:
        try:
            dated = dated.with_columns(
                pl.col("source_timestamp")
                .cast(pl.Utf8)
                .str.to_datetime(time_zone="UTC")
                .alias("source_timestamp")
            )
        except pl.exceptions.PolarsError as exc:
            raise NormalizationError(
                "source_timestamp contains a value that is not a timestamp"
            ) from exc
    return dated


def _coerce_measures(
    frame: pl.DataFrame,
    market_value_scale: float,
    weight_unit: WeightUnit,
) -> pl.DataFrame:
    for column in ("quantity", "market_value", "portfolio_weight"):
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(column))
            continue
        if frame.schema[column] in {pl.Utf8, pl.String}:
            frame = frame.with_columns(
                pl.when(pl.col(column).str.strip_chars() == "")
                .then(None)
                .otherwise(pl.col(column))
                .alias(column)
            )
        try:
            frame = frame.with_columns(pl.col(column).cast(pl.Float64, strict=True).alias(column))
        except pl.exceptions.PolarsError as exc:
            raise NormalizationError(f"{column} contains a non-numeric value") from exc
    frame = frame.with_columns(
        (pl.col("market_value") * pl.lit(market_value_scale)).alias("market_value")
    )
    if weight_unit == "percent":
        frame = frame.with_columns((pl.col("portfolio_weight") / 100.0).alias("portfolio_weight"))
    return frame


def _clean_upper(column: str) -> pl.Expr:
    text = pl.col(column).str.strip_chars().str.to_uppercase()
    return pl.when(text.is_null() | (text == "")).then(None).otherwise(text)


def _with_identifiers(frame: pl.DataFrame) -> pl.DataFrame:
    cik_digits = pl.col("cik").str.replace_all(r"[^0-9]", "")
    cik_padded = (
        pl.when(cik_digits.str.len_chars() > 0).then(cik_digits.str.zfill(10)).otherwise(None)
    )
    series = _clean_upper("series_id")
    explicit_fund = pl.col("fund_id").str.strip_chars()
    explicit_fund = (
        pl.when(explicit_fund.is_null() | (explicit_fund == "")).then(None).otherwise(explicit_fund)
    )
    derived_fund = (
        pl.when(cik_padded.is_not_null() & series.is_not_null())
        .then(pl.concat_str([pl.lit("cik:"), cik_padded, pl.lit("|series:"), series]))
        .otherwise(None)
    )

    cusip = _clean_upper("cusip")
    isin = _clean_upper("isin")
    security_ticker = _clean_upper("security_ticker")
    name_key = (
        pl.col("security_name").str.strip_chars().str.replace_all(r"\s+", " ").str.to_uppercase()
    )
    name_key = pl.when(name_key.is_null() | (name_key == "")).then(None).otherwise(name_key)
    security_id = pl.coalesce(
        [
            pl.when(cusip.is_not_null()).then(pl.concat_str([pl.lit("cusip:"), cusip])),
            pl.when(isin.is_not_null()).then(pl.concat_str([pl.lit("isin:"), isin])),
            pl.when(security_ticker.is_not_null()).then(
                pl.concat_str([pl.lit("ticker:"), security_ticker])
            ),
            pl.when(name_key.is_not_null()).then(pl.concat_str([pl.lit("name:"), name_key])),
        ]
    )
    return frame.with_columns(
        pl.coalesce([explicit_fund, derived_fund]).alias("fund_id"),
        security_id.alias("security_id"),
        cusip.alias("cusip"),
        isin.alias("isin"),
        security_ticker.alias("security_ticker"),
        series.alias("series_id"),
        cik_padded.alias("cik"),
        _clean_upper("ticker").alias("ticker"),
        _clean_upper("class_id").alias("class_id"),
        _clean_upper("currency").alias("currency"),
    )


def _reject_unidentified_rows(frame: pl.DataFrame) -> None:
    missing = frame.filter(
        pl.col("fund_id").is_null()
        | pl.col("security_id").is_null()
        | pl.col("snapshot_date").is_null()
    )
    if missing.height:
        raise NormalizationError(
            f"{missing.height} rows are missing snapshot_date, fund_id, or a security identifier. "
            "A ticker is not accepted as a fund id. Provide fund_id, or both cik and series_id, "
            "and at least one of cusip, isin, security_ticker, or security_name."
        )


def _duplicate_row_count(frame: pl.DataFrame) -> int:
    sizes = frame.group_by(_GROUP_KEYS).len()
    extras = sizes.filter(pl.col("len") > 1)
    if extras.is_empty():
        return 0
    total = extras.select((pl.col("len") - 1).sum()).item()
    return int(total or 0)


def _conflict_warnings(frame: pl.DataFrame) -> list[str]:
    conflicts = frame.group_by(_GROUP_KEYS).agg(
        [(pl.col(column).drop_nulls().n_unique() > 1).alias(column) for column in _CONFLICT_COLUMNS]
    )
    warnings: list[str] = []
    for column in _CONFLICT_COLUMNS:
        count = conflicts.filter(pl.col(column)).height
        if count:
            warnings.append(
                f"{count} security groups have conflicting {column} values; "
                "that field was stored as null for those groups"
            )
    return warnings


def _consistent(column: str) -> pl.Expr:
    unique = pl.col(column).drop_nulls().n_unique()
    return (
        pl.when(unique > 1)
        .then(pl.lit(None, dtype=pl.Utf8))
        .otherwise(pl.col(column).drop_nulls().first())
        .alias(column)
    )


def _sum_or_null(column: str) -> pl.Expr:
    return (
        pl.when(pl.col(column).is_not_null().any())
        .then(pl.col(column).sum())
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias(column)
    )


def _aggregate(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.group_by(_GROUP_KEYS).agg(
        [
            *[_consistent(column) for column in _CONFLICT_COLUMNS],
            _sum_or_null("quantity"),
            _sum_or_null("market_value"),
            _sum_or_null("portfolio_weight"),
            pl.col("source_timestamp").max().alias("source_timestamp"),
        ]
    )


def _derive_missing_weights(frame: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    keys = ["fund_id", "snapshot_date"]
    status = frame.group_by(keys).agg(
        [
            pl.col("portfolio_weight").is_null().all().alias("weights_missing"),
            pl.col("market_value").is_not_null().all().alias("values_complete"),
            pl.col("market_value").sum().alias("value_sum"),
        ]
    )
    derivable = status.filter(
        pl.col("weights_missing") & pl.col("values_complete") & (pl.col("value_sum") != 0)
    )
    blocked = status.filter(
        pl.col("weights_missing")
        & (~pl.col("values_complete") | pl.col("value_sum").is_null() | (pl.col("value_sum") == 0))
    )
    warnings: list[str] = []
    for fund_id, snapshot_date in derivable.select(keys).iter_rows():
        warnings.append(
            f"Derived portfolio_weight from market_value for {fund_id} on {snapshot_date}"
        )
    for fund_id, snapshot_date in blocked.select(keys).iter_rows():
        warnings.append(
            f"portfolio_weight is missing for {fund_id} on {snapshot_date} "
            "and could not be derived from market_value"
        )
    if derivable.is_empty():
        return frame, warnings

    marked = frame.join(
        derivable.select([*keys, pl.lit(True).alias("_derive")]),
        on=keys,
        how="left",
    )
    value_sum = pl.col("market_value").sum().over(keys)
    derived = marked.with_columns(
        pl.when(pl.col("_derive").fill_null(False))
        .then(pl.col("market_value") / value_sum)
        .otherwise(pl.col("portfolio_weight"))
        .alias("portfolio_weight")
    ).drop("_derive")
    return derived, warnings


def _weight_sum_warnings(frame: pl.DataFrame) -> list[str]:
    warnings: list[str] = []
    if frame.filter(pl.col("portfolio_weight").is_null()).height:
        warnings.append(
            "Some holdings have no portfolio_weight. Concentration and drift use only "
            "holdings whose weight was reported or derived."
        )
    totals = frame.group_by(["fund_id", "snapshot_date"]).agg(
        pl.col("portfolio_weight").sum().alias("weight_sum")
    )
    for fund_id, snapshot_date, weight_sum in totals.iter_rows():
        if weight_sum is None:
            continue
        if weight_sum > 1.5 or weight_sum < 0:
            warnings.append(
                f"Observed weights for {fund_id} on {snapshot_date} sum to {weight_sum:.4f}. "
                "Values were not rescaled. Confirm the weight unit."
            )
    return warnings


def _finalize_schema(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.schema.get("source_timestamp") != _DATETIME:
        frame = frame.with_columns(pl.col("source_timestamp").cast(_DATETIME))
    for column in ("quantity", "market_value", "portfolio_weight"):
        frame = frame.with_columns(pl.col(column).cast(pl.Float64))
    return frame.select(CANONICAL_COLUMNS).sort(["fund_id", "snapshot_date", "security_id"])
