"""Tests for the JSON transport the public-API clients share."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import requests

from the_front_office.adapters.outbound.platforms.cache import JsonDiskCache
from the_front_office.adapters.outbound.platforms.http import JsonApiClient
from the_front_office.adapters.outbound.platforms.retry import build_retry, is_transient
from the_front_office.domain.errors import FPLAPIError, SleeperAPIError

TTL = timedelta(hours=1)


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)  # type: ignore[arg-type]

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.requests: list[str] = []
        self.timeouts: list[int] = []

    def get(self, url: str, timeout: int = 0) -> FakeResponse:
        self.requests.append(url)
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


def _client(tmp_path: Path, session: FakeSession, error: type = SleeperAPIError) -> JsonApiClient:
    return JsonApiClient(
        name="Test",
        cache=JsonDiskCache(tmp_path / "c.json"),
        # No real backoff; the hermetic suite must not spend seconds sleeping.
        retry=lambda: build_retry(attempts=2, multiplier=1, min_wait=0, max_wait=0, predicate=is_transient).copy(
            wait=lambda _: 0
        ),
        error=error,
        session=session,
        timeout=11,
    )


def test_a_successful_get_returns_the_payload(tmp_path: Path) -> None:
    session = FakeSession({"ok": True})
    assert _client(tmp_path, session).get("https://example.test/a") == {"ok": True}
    assert session.timeouts == [11]


def test_a_call_can_override_the_default_timeout(tmp_path: Path) -> None:
    """The player catalogue is far larger than anything else and needs longer."""
    session = FakeSession({})
    _client(tmp_path, session).get("https://example.test/big", timeout=90)
    assert session.timeouts == [90]


def test_a_failure_becomes_the_callers_domain_error(tmp_path: Path) -> None:
    session = FakeSession(error=requests.exceptions.ConnectionError("down"))
    with pytest.raises(FPLAPIError, match="Test request failed"):
        _client(tmp_path, session, error=FPLAPIError).get("https://example.test/a")


def test_each_caller_gets_its_own_error_type(tmp_path: Path) -> None:
    """One transport, two platforms — a failure must not surface as the wrong one."""
    session = FakeSession(error=requests.exceptions.ConnectionError("down"))
    with pytest.raises(SleeperAPIError):
        _client(tmp_path, session, error=SleeperAPIError).get("https://example.test/a")


def test_a_transient_failure_is_retried(tmp_path: Path) -> None:
    session = FakeSession(error=requests.exceptions.Timeout())
    with pytest.raises(SleeperAPIError):
        _client(tmp_path, session).get("https://example.test/a")
    assert len(session.requests) == 2


def test_a_cached_value_is_served_without_a_second_request(tmp_path: Path) -> None:
    session = FakeSession({"n": 1})
    client = _client(tmp_path, session)
    assert client.cached("k", "https://example.test/a", TTL) == {"n": 1}
    assert client.cached("k", "https://example.test/a", TTL) == {"n": 1}
    assert len(session.requests) == 1


def test_an_expired_entry_is_refetched(tmp_path: Path) -> None:
    session = FakeSession({"n": 1})
    client = _client(tmp_path, session)
    client.cached("k", "https://example.test/a", timedelta(0))
    client.cached("k", "https://example.test/a", timedelta(0))
    assert len(session.requests) == 2


def test_a_caller_can_transform_before_storing(tmp_path: Path) -> None:
    """The catalogue is trimmed on the way in, so it bypasses `cached`."""
    client = _client(tmp_path, FakeSession())
    assert client.cache_get("k", TTL) is None
    client.cache_set("k", {"trimmed": True})
    assert client.cache_get("k", TTL) == {"trimmed": True}


def test_a_stored_value_survives_a_new_client_on_the_same_file(tmp_path: Path) -> None:
    _client(tmp_path, FakeSession()).cache_set("k", [1, 2])
    assert _client(tmp_path, FakeSession()).cache_get("k", TTL) == [1, 2]


def test_the_cache_is_keyed_not_url_addressed(tmp_path: Path) -> None:
    """Two URLs under one key is how a paginated endpoint is folded together."""
    session = FakeSession({"n": 1})
    client = _client(tmp_path, session)
    client.cached("same", "https://example.test/a", TTL)
    client.cached("same", "https://example.test/b", TTL)
    assert session.requests == ["https://example.test/a"]


def test_a_cache_entry_stores_when_it_was_written(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeSession())
    client.cache_set("k", 1)
    assert client.cache_get("k", timedelta(seconds=1)) == 1
    stale = JsonDiskCache(tmp_path / "c.json").get("k", timedelta(seconds=1), now=datetime.now(timezone.utc) + TTL)
    assert stale is None
