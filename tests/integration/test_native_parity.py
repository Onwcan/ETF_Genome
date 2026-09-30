"""Optional cross-language regression checks against the Python shock engine.

Set ETF_GENOME_NATIVE_BINARY to a built executable to enable these tests.
Windows can additionally set ETF_GENOME_NATIVE_WSL_DISTRO to run a Linux binary.
"""

from __future__ import annotations

import csv
import io
import os
import subprocess
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from etf_genome.graph.native_export import demo_inputs, export_native_inputs
from etf_genome.graph.shock import run_shock

pytestmark = pytest.mark.skipif(
    not os.environ.get("ETF_GENOME_NATIVE_BINARY"), reason="Native binary not configured"
)


def _execute_native(*arguments: str | Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    binary = os.environ["ETF_GENOME_NATIVE_BINARY"]
    distro = os.environ.get("ETF_GENOME_NATIVE_WSL_DISTRO")
    command = [binary]
    values = [str(argument) for argument in arguments]
    if distro:
        prefix = ["wsl.exe", "--distribution", distro, "--exec"]
        for index, argument in enumerate(arguments):
            if isinstance(argument, Path):
                values[index] = subprocess.run(
                    [*prefix, "wslpath", "-a", str(argument)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ).stdout.strip()
        command = [*prefix, binary]
    return subprocess.run(
        [*command, *values],
        check=check,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_native(
    edge_path: Path, shock_path: Path, *, snapshot: bool = False
) -> list[dict[str, str]]:
    result = _execute_native(
        "shock", "--snapshot" if snapshot else "--edges", edge_path, "--shocks", shock_path
    )
    return list(csv.DictReader(io.StringIO(result.stdout)))


def _assert_parity(edges: pl.DataFrame, shocks: dict[str, float], tmp_path: Path) -> None:
    edge_path, shock_path = export_native_inputs(edges, shocks, tmp_path)
    actual = _run_native(edge_path, shock_path)
    expected = run_shock(edges, shocks, scenario_id="parity", snapshot_date=date(2024, 1, 1))
    assert len(actual) == len(expected.impacts)
    for row, impact in zip(actual, expected.impacts, strict=True):
        assert row["etf_node_id"] == impact.etf_node_id
        assert float(row["direct_shock"]) == pytest.approx(impact.direct_shock, abs=1e-12)
        assert float(row["covered_weight"]) == pytest.approx(impact.covered_weight, abs=1e-12)
        assert float(row["weight_sum"]) == pytest.approx(impact.weight_sum, abs=1e-12)
        assert int(row["missing_weight_count"]) == impact.missing_weight_count


def test_native_matches_python_signed_and_missing_weights(tmp_path: Path) -> None:
    edges, shocks = demo_inputs()
    _assert_parity(edges, shocks, tmp_path)


def test_native_matches_python_ambiguous_aliases_and_quoted_fields(tmp_path: Path) -> None:
    edges = pl.DataFrame(
        {
            "etf_node_id": ['fund,"A"', 'fund,"A"', "fund:B", "fund:B", "fund:B"],
            "security_node_id": ["demo:one", "demo:two", "demo:one", "demo:three", "demo:four"],
            "security_ticker": ["DUP", "DUP", "DUP", "THREE", None],
            "portfolio_weight": [0.2, -0.1, None, 0.6, 0.0],
        }
    )
    # DUP is ambiguous. Canonical id then alias override is processed in input order.
    shocks = {"DUP": -0.5, "demo:one": -0.1, "demo:three": 0.1, "three": -0.2, "unknown": 1.0}
    _assert_parity(edges, shocks, tmp_path)


def test_binary_snapshot_preserves_csv_shock_results(tmp_path: Path) -> None:
    edges, shocks = demo_inputs()
    edge_path, shock_path = export_native_inputs(edges, shocks, tmp_path)
    snapshot = tmp_path / "graph.bin"
    _execute_native("snapshot-save", "--edges", edge_path, "--output", snapshot)
    assert _run_native(snapshot, shock_path, snapshot=True) == _run_native(edge_path, shock_path)
    assert '"snapshot_version":1' in _execute_native("snapshot-info", snapshot).stdout
    snapshot.write_bytes(snapshot.read_bytes()[:-1])
    result = _execute_native("snapshot-info", snapshot, check=False)
    assert result.returncode == 2
    assert "Truncated" in result.stderr


def test_snapshot_export_does_not_overwrite_source_alias(tmp_path: Path) -> None:
    edges, shocks = demo_inputs()
    edge_path, _ = export_native_inputs(edges, shocks, tmp_path)
    original = edge_path.read_bytes()
    alias = tmp_path / "source-alias.csv"
    os.link(edge_path, alias)
    result = _execute_native("snapshot-save", "--edges", edge_path, "--output", alias, check=False)
    assert result.returncode == 2
    assert "must not replace" in result.stderr
    assert edge_path.read_bytes() == original
