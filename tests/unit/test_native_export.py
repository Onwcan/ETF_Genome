"""Verify the Python/native boundary preserves financial meaning and privacy."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import polars as pl
import pytest

from etf_genome.graph.native_export import _load_scenario, demo_inputs, export_native_inputs


def test_export_preserves_signed_and_missing_weights_and_excludes_metadata(tmp_path: Path) -> None:
    edges, shocks = demo_inputs()
    edges = edges.with_columns(pl.lit("private metadata").alias("local_path"))
    edge_path, shock_path = export_native_inputs(edges, shocks, tmp_path)
    with edge_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == [
            "etf_node_id",
            "security_node_id",
            "security_ticker",
            "portfolio_weight",
        ]
        rows = list(reader)
    assert float(rows[3]["portfolio_weight"]) == -0.1
    assert rows[4]["portfolio_weight"] == ""
    assert "private metadata" not in edge_path.read_text(encoding="utf-8")
    with shock_path.open(encoding="utf-8", newline="") as stream:
        exported_shocks = {row["key"]: float(row["shock"]) for row in csv.DictReader(stream)}
    assert exported_shocks == shocks


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_export_rejects_nonfinite_inputs_before_writing(tmp_path: Path, value: float) -> None:
    edges, shocks = demo_inputs()
    with pytest.raises(ValueError, match="finite"):
        export_native_inputs(edges, {"ALPHA": value}, tmp_path / "invalid")
    edges = edges.with_columns(pl.lit(value).alias("portfolio_weight"))
    with pytest.raises(ValueError, match="finite"):
        export_native_inputs(edges, shocks, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_export_quotes_csv_fields_and_keeps_null_tickers(tmp_path: Path) -> None:
    edges = pl.DataFrame(
        {
            "etf_node_id": ['fund,"quoted"'],
            "security_node_id": ["demo:one"],
            "security_ticker": [None],
            "portfolio_weight": [1.0],
        }
    )
    path, _ = export_native_inputs(edges, {}, tmp_path)
    with path.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["etf_node_id"] == 'fund,"quoted"'
    assert row["security_ticker"] == ""


@pytest.mark.parametrize("value", ['"0.1"', "true", "null"])
def test_scenario_rejects_nonnumeric_values(tmp_path: Path, value: str) -> None:
    path = tmp_path / "scenario.json"
    path.write_text('{"shocks": {"ALPHA": ' + value + "}}", encoding="utf-8")
    with pytest.raises(ValueError, match="numbers"):
        _load_scenario(path)


def test_export_rejects_control_characters(tmp_path: Path) -> None:
    edges, shocks = demo_inputs()
    edges = edges.with_columns(pl.lit("fund\nother").alias("etf_node_id"))
    with pytest.raises(ValueError, match="control"):
        export_native_inputs(edges, shocks, tmp_path)
