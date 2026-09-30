"""File cache for HTTP response bodies."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path


class FileResponseCache:
    """Store response bodies on disk with a time-to-live.

    A TTL of zero disables the cache. Cache files are content plus a small
    metadata sidecar. The cache key is a hash, so the URL is not used as a
    path component.
    """

    def __init__(
        self,
        directory: Path,
        ttl_seconds: int,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._directory = directory
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.time

    def get(self, url: str) -> bytes | None:
        if self._ttl_seconds <= 0:
            return None
        body_path, meta_path = self._paths(url)
        if not body_path.is_file() or not meta_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            stored_at = float(meta["stored_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if self._clock() - stored_at > self._ttl_seconds:
            return None
        try:
            return body_path.read_bytes()
        except OSError:
            return None

    def set(self, url: str, content: bytes) -> None:
        if self._ttl_seconds <= 0:
            return
        self._directory.mkdir(parents=True, exist_ok=True)
        body_path, meta_path = self._paths(url)
        temporary_body = body_path.with_suffix(".body.tmp")
        temporary_meta = meta_path.with_suffix(".json.tmp")
        temporary_body.write_bytes(content)
        temporary_meta.write_text(
            json.dumps({"stored_at": self._clock(), "url_sha256": self._key(url)}),
            encoding="utf-8",
        )
        temporary_body.replace(body_path)
        temporary_meta.replace(meta_path)

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = self._key(url)
        return self._directory / f"{key}.body", self._directory / f"{key}.meta.json"

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()
