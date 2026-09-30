"""SEC access errors."""

from __future__ import annotations

from etf_genome.errors import EtfGenomeError


class SecError(EtfGenomeError):
    """Base error for the SEC client."""


class SecConfigError(SecError):
    """Raised when live SEC access is not configured safely."""


class SecHttpError(SecError):
    """Raised for a non-success HTTP status that will not be retried, or the last retry."""

    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"SEC request to {url} failed with HTTP {status_code}")


class SecTimeoutError(SecError):
    """Raised when the transport times out."""


class SecTransportError(SecError):
    """Raised when the transport fails before an HTTP response."""

    def __init__(self, message: str, *, kind: str = "transport") -> None:
        super().__init__(message)
        self.kind = kind


class SecRetryExhausted(SecError):
    """Raised when every allowed attempt has failed."""

    def __init__(self, url: str, attempts: int) -> None:
        self.url = url
        self.attempts = attempts
        super().__init__(f"SEC request failed after {attempts} attempts: {url}")
