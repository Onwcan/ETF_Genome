"""Logging tests."""

from __future__ import annotations

import json
import logging

import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.logging_config import JsonLineFormatter, configure_logging, redact


def test_redact_hides_query_secrets_and_bearer_tokens() -> None:
    text = redact("calling api_key=supersecret Authorization: Bearer abc.def-ghi")
    assert "supersecret" not in text
    assert "abc.def-ghi" not in text
    assert "[REDACTED]" in text


def test_file_log_is_redacted(settings: AppSettings) -> None:
    logger = configure_logging(settings)
    logger.info("download failed api_key=supersecret")
    logger.info("header Authorization: Bearer abc.def-ghi")
    for handler in logger.handlers:
        handler.flush()
    text = (settings.log_dir / "etf_genome.log").read_text(encoding="utf-8")
    assert "supersecret" not in text
    assert "abc.def-ghi" not in text
    assert "download failed" in text


@pytest.mark.parametrize("scheme", ["Bearer", "Token", "Basic"])
def test_redact_removes_full_authorization_values(scheme: str) -> None:
    text = redact(f"request Authorization: {scheme} synthetic-credential+/= status=401")
    assert text == f"request Authorization: {scheme} [REDACTED] status=401"
    assert redact(text) == text


def test_redact_preserves_json_and_query_context() -> None:
    payload = {
        "api_key": "synthetic secret with spaces",
        "authorization": "Token synthetic-token",
        "client_secret": "synthetic-client-secret",
        "refresh_token": "synthetic-refresh-token",
        "provider": "fixture",
    }
    sanitized = json.loads(redact(json.dumps(payload)))
    assert sanitized == {
        "api_key": "[REDACTED]",
        "authorization": "Token [REDACTED]",
        "client_secret": "[REDACTED]",
        "refresh_token": "[REDACTED]",
        "provider": "fixture",
    }
    assert redact("https://example.com?apikey=synthetic&symbol=QQQ") == (
        "https://example.com?apikey=[REDACTED]&symbol=QQQ"
    )
    assert redact("{'password': 'synthetic pass', 'attempt': 2}") == (
        "{'password': '[REDACTED]', 'attempt': 2}"
    )


def test_json_formatter_redacts_context_and_exception() -> None:
    try:
        raise ValueError("Authorization: Basic synthetic-basic-credential")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "etf_genome", logging.ERROR, __file__, 1, "request failed", (), sys.exc_info()
        )
    record.url = "https://example.com?api_key=synthetic-query-secret&symbol=QQQ"
    payload = json.loads(JsonLineFormatter().format(record))
    assert payload["message"] == "request failed"
    assert payload["url"].endswith("api_key=[REDACTED]&symbol=QQQ")
    assert "synthetic" not in payload["exception"]
    assert "Basic [REDACTED]" in payload["exception"]
