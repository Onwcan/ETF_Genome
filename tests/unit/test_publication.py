"""The publication guard checks the actual index and never echoes secrets."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_publication import publication_findings, scan_file


def test_scan_reports_location_without_echoing_credential_or_contact() -> None:
    credential = "gh" + "p_" + "A" * 36
    contact = "private.person" + "@" + "mail.invalid-domain.com"
    source = f'api_key = "{credential}"\ncontact = "{contact}"\n'.encode()
    findings = scan_file("configs/local.toml", source)
    assert {finding.line for finding in findings} == {1, 2}
    assert "GitHub token" in {finding.reason for finding in findings}
    assert credential not in repr(findings)
    assert contact not in repr(findings)


def test_examples_and_synthetic_fixtures_pass() -> None:
    assert not scan_file(".env.example", b"# Example tester@example.com\n# API_KEY=\n")
    assert not scan_file("tests/fixtures/sample.json", b'{"token": "local-test-key"}')
    assert not scan_file("data/raw/.gitkeep", b"")


def test_private_and_generated_artifacts_are_rejected() -> None:
    for path in (
        ".env",
        ".env.prod",
        "models/registry.json",
        "data/prices.csv",
        ".venv-graph/a.py",
        "build/a.txt",
    ):
        assert scan_file(path, b"innocent text")[0].reason == "private/generated artifact"


def test_staged_scan_reads_index_even_after_worktree_is_cleaned(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    path = tmp_path / "config.txt"
    path.write_text("private" + ".contact@" + "personal-domain.net", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "config.txt"], check=True, capture_output=True
    )
    path.write_text("safe placeholder@example.com", encoding="utf-8")
    count, findings = publication_findings(tmp_path, staged=True)
    assert count == 1
    assert findings[0].reason == "non-placeholder email address"
    assert not publication_findings(tmp_path)[1]
