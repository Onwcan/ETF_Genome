"""Tracking metadata stays useful without copying credentials or contacts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_genome.experiments.tracking import ResearchTracker


def test_tracking_recursively_scrubs_private_metadata(tmp_path: Path) -> None:
    config = {
        "seed": 42,
        "feature_keys": ["return_1d", "volatility_20d"],
        "api_key": "synthetic-api-credential",
        "parameters": {
            "max_depth": 3,
            "client_secret": "synthetic-client-credential",
            "access_token": "synthetic-access-credential",
            "password": "synthetic-password",
            "authorization": "Token synthetic-auth-credential",
            "sec_user_agent": "Fixture developer@example.com",
            "contact_email": "developer@example.com",
        },
        "notes": [
            "Owner developer@example.com; keep seed 42",
            {"eta": 0.1, "refresh_token": "synthetic-refresh-credential"},
            "retry Authorization: Basic synthetic-basic-credential status=401",
        ],
    }
    original = json.dumps(config, sort_keys=True)
    tracker = ResearchTracker("none", root=tmp_path, run_name="fixture", config=config)
    assert tracker.config["seed"] == 42
    assert tracker.config["feature_keys"] == ["return_1d", "volatility_20d"]
    assert tracker.config["parameters"] == {"max_depth": 3}
    assert tracker.config["notes"] == [
        "Owner [REDACTED_EMAIL]; keep seed 42",
        {"eta": 0.1},
        "retry Authorization: Basic [REDACTED] status=401",
    ]
    serialized = json.dumps(tracker.config)
    assert "synthetic" not in serialized
    assert "developer@example.com" not in serialized
    assert json.dumps(config, sort_keys=True) == original


def test_tracking_passes_only_scrubbed_config_to_wandb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def init(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(id="fixture-run")

    monkeypatch.setitem(__import__("sys").modules, "wandb", SimpleNamespace(init=init))
    monkeypatch.delenv("WANDB_MODE", raising=False)
    tracker = ResearchTracker(
        "wandb",
        root=tmp_path,
        run_name="fixture developer@example.com",
        config={"seed": 42, "nested": [{"token": "synthetic-credential", "nthread": 1}]},
    )
    result = tracker.start()
    assert result.wandb_mode == "offline"
    assert calls[0]["name"] == "fixture [REDACTED_EMAIL]"
    assert calls[0]["config"] == {"seed": 42, "nested": [{"nthread": 1}]}
