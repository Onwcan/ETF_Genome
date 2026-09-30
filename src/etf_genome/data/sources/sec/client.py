"""Polite, cached, bounded-retry client for SEC HTTP endpoints.

The client does not download bulk archives. Callers request one URL at a time.
Live use also requires ``feature_flags.live_sec_fetch`` and a contact User-Agent.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.sec.errors import (
    SecConfigError,
    SecHttpError,
    SecRetryExhausted,
    SecTimeoutError,
    SecTransportError,
)
from etf_genome.data.sources.sec.transport import (
    HttpTransport,
    HttpxTransport,
    TransportFailure,
    TransportTimeout,
)
from etf_genome.data.storage.http_cache import FileResponseCache

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


class SecClient:
    """GET client with timeout, exponential backoff, and a minimum interval."""

    def __init__(
        self,
        settings: AppSettings,
        transport: HttpTransport | None = None,
        cache: FileResponseCache | None = None,
        *,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or HttpxTransport()
        self._cache = cache or FileResponseCache(
            settings.cache_dir / "sec",
            settings.sec_cache_ttl_seconds,
        )
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic
        self._last_request_at: float | None = None
        self._inflight_guard = threading.Lock()
        self._inflight: dict[str, threading.Lock] = {}

    def close(self) -> None:
        closer = getattr(self._transport, "close", None)
        if closer is not None:
            closer()

    def get_bytes(self, url: str, *, use_cache: bool = True) -> bytes:
        """Return the response body for ``url``.

        ``use_cache=False`` always contacts the origin when the request is made.
        Identical in-flight URLs share one download.
        """

        lock = self._url_lock(url)
        with lock:
            if use_cache:
                cached = self._cache.get(url)
                if cached is not None:
                    logger.info(
                        "Using cached SEC response",
                        extra={"url": url, "cache_hit": True, "provider": "sec"},
                    )
                    return cached
            return self._download(url, use_cache=use_cache)

    def _url_lock(self, url: str) -> threading.Lock:
        with self._inflight_guard:
            lock = self._inflight.get(url)
            if lock is None:
                lock = threading.Lock()
                self._inflight[url] = lock
            return lock

    def _download(self, url: str, *, use_cache: bool) -> bytes:

        self._require_user_agent()
        attempts = self._settings.sec_max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            self._respect_rate_interval()
            try:
                response = self._transport.get(
                    url,
                    headers=self._headers(),
                    timeout=self._settings.sec_timeout_seconds,
                )
            except TransportTimeout as exc:
                last_error = SecTimeoutError(f"Timed out requesting {url}")
                last_error.__cause__ = exc
                logger.warning(
                    "SEC request timed out",
                    extra={"url": url, "attempt": attempt + 1},
                )
            except TransportFailure as exc:
                last_error = SecTransportError(
                    f"Transport failed for {url}",
                    kind=exc.kind,
                )
                last_error.__cause__ = exc
                logger.warning(
                    "SEC transport failure",
                    extra={"url": url, "attempt": attempt + 1, "provider": "sec"},
                )
            else:
                if response.status_code == 200:
                    if len(response.content) > self._settings.sec_max_response_bytes:
                        raise SecTransportError(
                            f"SEC response exceeded {self._settings.sec_max_response_bytes} bytes",
                            kind="validation",
                        )
                    if use_cache:
                        self._cache.set(url, response.content)
                    logger.info(
                        "SEC request completed",
                        extra={
                            "url": url,
                            "status_code": response.status_code,
                            "download_bytes": len(response.content),
                            "cache_hit": False,
                            "provider": "sec",
                            "attempt": attempt + 1,
                        },
                    )
                    return response.content
                last_error = SecHttpError(response.status_code, url)
                logger.warning(
                    "SEC HTTP error",
                    extra={
                        "url": url,
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                    },
                )
                if response.status_code not in _RETRYABLE_STATUS:
                    raise last_error
                if attempt < attempts - 1:
                    self._sleep_backoff(attempt, response.headers.get("retry-after"))
                continue

            if attempt < attempts - 1:
                self._sleep_backoff(attempt, None)

        raise SecRetryExhausted(url, attempts) from last_error

    def get_json(self, url: str, *, use_cache: bool = True) -> Any:
        """Return parsed JSON from ``url``."""

        try:
            return json.loads(self.get_bytes(url, use_cache=use_cache))
        except json.JSONDecodeError as exc:
            raise SecTransportError(f"SEC response was not valid JSON: {url}") from exc

    def fetch_submissions(self, cik: str, *, use_cache: bool = False) -> Any:
        """Fetch one company submissions document.

        This is a single-URL request. It does not walk filing indexes or
        download N-PORT archives.
        """

        digits = "".join(character for character in cik if character.isdigit())
        if not digits:
            raise SecConfigError("CIK must contain digits")
        url = _SUBMISSIONS_URL.format(cik=digits.zfill(10))
        payload = self.get_json(url, use_cache=use_cache)
        if not isinstance(payload, dict):
            raise SecTransportError(f"Unexpected submissions payload from {url}")
        return payload

    def _require_user_agent(self) -> None:
        if not self._settings.sec_user_agent_is_configured():
            raise SecConfigError(
                "Set ETF_GENOME_SEC_USER_AGENT to an application name and contact "
                "email before calling the SEC. The placeholder user agent is rejected "
                "so requests stay within SEC fair-access guidance."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._settings.sec_user_agent.strip(),
            "Accept": "application/json,text/plain,*/*",
        }

    def _respect_rate_interval(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self._settings.sec_min_interval_seconds - elapsed
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock()
        self._last_request_at = now

    def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = self._settings.sec_backoff_seconds * (self._settings.sec_backoff_factor**attempt)
        if retry_after is not None:
            try:
                declared = float(retry_after)
            except ValueError:
                declared = 0.0
            if declared > 0:
                delay = max(delay, declared)
        delay = min(delay, self._settings.sec_backoff_cap_seconds)
        logger.info(
            "Waiting before SEC retry",
            extra={"attempt": attempt + 1},
        )
        self._sleeper(delay)


def fetch_submissions_if_enabled(settings: AppSettings, cik: str) -> Any:
    """Fetch one submissions document when the live-SEC feature flag is on."""

    if not settings.feature_flags.live_sec_fetch:
        raise SecConfigError(
            "Live SEC fetch is disabled. Set ETF_GENOME_FEATURE_FLAGS__LIVE_SEC_FETCH=true "
            "after configuring ETF_GENOME_SEC_USER_AGENT."
        )
    settings.ensure_directories()
    return SecClient(settings).fetch_submissions(cik)
