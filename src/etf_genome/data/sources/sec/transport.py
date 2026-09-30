"""HTTP transport interfaces for the SEC client.

The client depends on this small surface so tests can substitute a fake
transport. Nothing in here knows about holdings or filings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

_SEC_HOSTS = frozenset({"www.sec.gov", "data.sec.gov", "efts.sec.gov"})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


class TransportTimeout(Exception):
    """The underlying HTTP client timed out."""


class TransportFailure(Exception):
    """The underlying HTTP client failed without a response."""

    def __init__(self, message: str, *, kind: str = "transport") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class HttpResponse:
    """Minimal HTTP response retained by the SEC client."""

    status_code: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)


class HttpTransport(Protocol):
    """GET-only transport. Implementations must not retry on their own."""

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Perform one HTTP GET."""


class HttpxTransport:
    """httpx-backed transport used for real SEC requests."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(follow_redirects=False, verify=True)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        current = url
        try:
            for _ in range(4):
                response = self._client.get(current, headers=headers, timeout=timeout)
                if response.status_code in _REDIRECTS:
                    current = _https_sec_redirect(current, response.headers.get("location"))
                    continue
                return HttpResponse(
                    status_code=response.status_code,
                    content=response.content,
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except TransportFailure:
            raise
        except httpx.TimeoutException as exc:
            raise TransportTimeout(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise TransportFailure(str(exc), kind="offline") from exc
        except httpx.HTTPError as exc:
            raise TransportFailure(str(exc)) from exc
        raise TransportFailure("SEC redirect limit exceeded", kind="rejected")


def _https_sec_redirect(current: str, location: str | None) -> str:
    if location is None or not location.strip():
        raise TransportFailure("SEC redirect did not include a location", kind="rejected")
    target = urljoin(current, location.strip())
    parsed = urlparse(target)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _SEC_HOSTS:
        raise TransportFailure("Refused a redirect that left SEC over HTTPS", kind="rejected")
    return target
