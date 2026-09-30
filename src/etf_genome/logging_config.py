"""Structured logging for development consoles and rotating local files.

Messages are passed through a redaction step so common credential query
parameters are not written to disk or the console.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Final

from etf_genome.config.settings import AppSettings

_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?P<prefix>\b(?P<name>api[_-]?key|(?:access|refresh)[_-]?token|token|"
    r"(?:client[_-]?)?secret(?:[_-]?key)?|password|authorization)"
    r"[\"']?\s*[:=]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"(?:Bearer|Token|Basic)\s+(?:\[REDACTED\]|[^\s,;&}\]]+)|"
    r"\[REDACTED\]|[^\s,;&}\]]+)"
)
_BEARER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\bBearer\s+(?:\[REDACTED\]|[A-Za-z0-9._~+/=\-]+)"
)
_AUTH_SCHEME_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?i)^(Bearer|Token|Basic)\s+")
_LOGGER_NAME: Final[str] = "etf_genome"
_EXTRA_KEYS: Final[tuple[str, ...]] = (
    "fund_id",
    "snapshot_date",
    "url",
    "status_code",
    "attempt",
    "path",
    "provider",
    "cik",
    "accession",
    "operation",
    "elapsed_ms",
    "cache_hit",
    "download_bytes",
    "result",
)


def redact(text: str) -> str:
    """Remove credential-shaped fragments from a log line."""

    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    return _SECRET_PATTERN.sub(_redact_assignment, redacted)


def _redact_assignment(match: re.Match[str]) -> str:
    """Keep quotes and authentication schemes without retaining their values."""

    value = match.group("value")
    quote = value[0] if value[0] in {'"', "'"} else ""
    unquoted = value[1:-1] if quote else value
    scheme = ""
    if match.group("name").lower() == "authorization":
        auth = _AUTH_SCHEME_PATTERN.match(unquoted)
        if auth is not None:
            scheme = auth.group(1) + " "
    return match.group("prefix") + quote + scheme + "[REDACTED]" + quote


class RedactingFormatter(logging.Formatter):
    """Apply :func:`redact` to the fully formatted log line."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class JsonLineFormatter(logging.Formatter):
    """Write one JSON object per line, including a small set of context fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key in _EXTRA_KEYS:
            if key in record.__dict__:
                payload[key] = redact(str(record.__dict__[key]))
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: AppSettings) -> logging.Logger:
    """Attach console and rotating file handlers to the ``etf_genome`` logger.

    Calling this more than once replaces previous handlers so tests and the
    desktop shell can reconfigure a process safely.
    """

    settings.ensure_directories()
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.log_dir / "etf_genome.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(JsonLineFormatter())
    logger.addHandler(file_handler)
    logger.debug("Logging configured at %s", settings.log_level)
    return logger
