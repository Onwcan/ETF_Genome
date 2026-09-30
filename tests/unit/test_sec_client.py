"""SEC client tests. The transport is fake, so these tests make no network calls."""

from __future__ import annotations

import pytest

from etf_genome.config.settings import AppSettings
from etf_genome.data.sources.sec.client import SecClient, fetch_submissions_if_enabled
from etf_genome.data.sources.sec.errors import (
    SecConfigError,
    SecHttpError,
    SecRetryExhausted,
)
from etf_genome.data.sources.sec.transport import HttpResponse, TransportTimeout
from etf_genome.data.storage.http_cache import FileResponseCache


class ScriptedTransport:
    """Return a prepared sequence of responses or exceptions."""

    def __init__(self, script: list[HttpResponse | Exception]) -> None:
        self.script = list(script)
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse:
        self.urls.append(url)
        self.headers.append(headers)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def _client(
    settings: AppSettings,
    transport: ScriptedTransport,
    *,
    retries: int = 2,
    min_interval: float = 0.0,
    ttl: int = 60,
) -> tuple[SecClient, Clock, list[float]]:
    clock = Clock()
    sleeps: list[float] = []

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    tuned = settings.model_copy(
        update={
            "sec_max_retries": retries,
            "sec_backoff_seconds": 0.25,
            "sec_backoff_factor": 2.0,
            "sec_backoff_cap_seconds": 1.0,
            "sec_min_interval_seconds": min_interval,
            "sec_cache_ttl_seconds": ttl,
        }
    )
    cache = FileResponseCache(tuned.cache_dir / "sec", ttl, clock=clock)
    client = SecClient(tuned, transport, cache, sleeper=sleeper, clock=clock)
    return client, clock, sleeps


def test_placeholder_user_agent_is_rejected(tmp_path_factory: pytest.TempPathFactory) -> None:
    settings = AppSettings(
        data_dir=tmp_path_factory.mktemp("sec"),
        sec_user_agent="ETF Genome Phase1 (research; set ETF_GENOME_SEC_USER_AGENT)",
    )
    transport = ScriptedTransport([HttpResponse(200, b"{}")])
    client, _clock, _sleeps = _client(settings, transport)
    with pytest.raises(SecConfigError):
        client.get_bytes("https://data.sec.gov/submissions/CIK0000000001.json")
    assert transport.urls == []


def test_not_found_is_not_retried(settings: AppSettings) -> None:
    transport = ScriptedTransport([HttpResponse(404, b"missing")])
    client, _clock, sleeps = _client(settings, transport)
    with pytest.raises(SecHttpError) as caught:
        client.get_bytes("https://data.sec.gov/example.json")
    assert caught.value.status_code == 404
    assert transport.urls == ["https://data.sec.gov/example.json"]
    assert sleeps == []


def test_server_error_retries_then_succeeds(settings: AppSettings) -> None:
    transport = ScriptedTransport(
        [
            HttpResponse(503, b"busy", {"retry-after": "0.5"}),
            HttpResponse(200, b'{"ok": true}'),
        ]
    )
    client, _clock, sleeps = _client(settings, transport, retries=2)
    assert client.get_bytes("https://data.sec.gov/example.json") == b'{"ok": true}'
    assert len(transport.urls) == 2
    assert sleeps == [0.5]
    assert transport.headers[0]["User-Agent"] == settings.sec_user_agent


def test_retries_stop_at_the_configured_limit(settings: AppSettings) -> None:
    transport = ScriptedTransport([TransportTimeout("slow"), TransportTimeout("slow")])
    client, _clock, sleeps = _client(settings, transport, retries=1)
    with pytest.raises(SecRetryExhausted) as caught:
        client.get_bytes("https://data.sec.gov/example.json")
    assert caught.value.attempts == 2
    assert len(transport.urls) == 2
    assert sleeps == [0.25]


def test_cache_prevents_a_second_request(settings: AppSettings) -> None:
    transport = ScriptedTransport([HttpResponse(200, b"cached-body")])
    client, _clock, _sleeps = _client(settings, transport)
    assert client.get_bytes("https://data.sec.gov/example.json") == b"cached-body"
    assert client.get_bytes("https://data.sec.gov/example.json") == b"cached-body"
    assert len(transport.urls) == 1


def test_minimum_interval_is_enforced(settings: AppSettings) -> None:
    transport = ScriptedTransport([HttpResponse(200, b"one"), HttpResponse(200, b"two")])
    client, _clock, sleeps = _client(settings, transport, min_interval=0.2, ttl=0)
    client.get_bytes("https://data.sec.gov/one.json")
    client.get_bytes("https://data.sec.gov/two.json")
    assert sleeps == [0.2]


def test_submissions_url_pads_the_cik(settings: AppSettings) -> None:
    transport = ScriptedTransport([HttpResponse(200, b'{"cik": "1999999"}')])
    client, _clock, _sleeps = _client(settings, transport)
    payload = client.fetch_submissions("1999999")
    assert payload["cik"] == "1999999"
    assert transport.urls == ["https://data.sec.gov/submissions/CIK0001999999.json"]


def test_live_fetch_stays_disabled_by_default(settings: AppSettings) -> None:
    with pytest.raises(SecConfigError, match="disabled"):
        fetch_submissions_if_enabled(settings, "1999999")
