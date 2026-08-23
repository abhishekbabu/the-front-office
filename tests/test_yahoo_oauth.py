"""Tests for the Yahoo OAuth2 handshake.

The browser half cannot be exercised hermetically, so what is asserted here is
the half that was wrong: which parameters go out, and that the two halves agree
about the redirect URI.
"""

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from the_front_office.adapters.outbound.platforms.yahoo import oauth
from the_front_office.domain.errors import YahooLoginRequiredError

REDIRECT = "https://localhost:8080"


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the token exchange without making one."""
    calls: list[dict[str, Any]] = []

    def _post(url: str, data: dict[str, Any], timeout: int = 0) -> FakeResponse:
        calls.append(data)
        return FakeResponse({"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "fspt-r"})

    monkeypatch.setattr(oauth.requests, "post", _post)
    return calls


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Capture what would be persisted, rather than writing a token file."""
    import yahoofantasy.util.persistence as persistence

    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(persistence, "save", lambda key, value, **kw: calls.append((key, value)))
    return calls


@pytest.fixture
def authorised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the browser, returning a code as though someone had clicked."""
    monkeypatch.setattr(oauth, "_capture_code", lambda redirect_uri, client_id, scope: "the-code")


# ── the bug this module exists for ──────────────────────────────────────


def test_the_exchange_quotes_back_the_same_redirect_uri(
    posted: list[dict[str, Any]], saved: list[Any], authorised: None
) -> None:
    """RFC 6749 §4.1.3 requires it, and Yahoo answers a mismatch with a token
    rather than an error — one that authenticates and grants nothing."""
    oauth.authorise("id", "secret", REDIRECT)

    assert posted[0]["redirect_uri"] == REDIRECT
    assert posted[0]["redirect_uri"] != "oob"


def test_the_exchange_sends_an_authorization_code_grant(
    posted: list[dict[str, Any]], saved: list[Any], authorised: None
) -> None:
    oauth.authorise("id", "secret", REDIRECT)

    assert posted[0]["grant_type"] == "authorization_code"
    assert posted[0]["code"] == "the-code"
    assert posted[0]["client_id"] == "id"


def test_fantasy_read_is_requested_explicitly(
    monkeypatch: pytest.MonkeyPatch, posted: list[Any], saved: list[Any]
) -> None:
    """Leaving scope to be inferred is what makes an empty grant possible."""
    seen: list[str] = []
    monkeypatch.setattr(oauth, "_capture_code", lambda redirect_uri, client_id, scope: seen.append(scope) or "c")

    oauth.authorise("id", "secret", REDIRECT)

    assert seen == ["fspt-r"]


# ── the authorization request ───────────────────────────────────────────


def test_the_authorization_url_carries_every_parameter_yahoo_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(oauth.webbrowser, "open_new_tab", lambda url: opened.append(url))
    # Fail the wait immediately; the URL is what is under test.
    monkeypatch.setattr(oauth, "CALLBACK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(oauth, "_certificate", lambda: None)

    with pytest.raises(YahooLoginRequiredError):
        oauth._capture_code(REDIRECT, "the-id", "fspt-r")

    # No certificate means the server was never started, so nothing opened.
    assert opened == []


def test_the_url_is_built_from_the_same_redirect_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """Built here and quoted back in the exchange; they must not drift apart."""
    captured: dict[str, list[str]] = {}

    def _open(url: str) -> None:
        captured.update(parse_qs(urlparse(url).query))
        raise RuntimeError("stop before the wait")

    monkeypatch.setattr(oauth.webbrowser, "open_new_tab", _open)

    class _Server:
        def __init__(self, *a: Any, **k: Any) -> None: ...

        socket = None

        def server_close(self) -> None: ...

    monkeypatch.setattr(oauth, "HTTPServer", _Server)

    with pytest.raises(RuntimeError):
        oauth._capture_code("http://localhost:9999", "the-id", "fspt-r")

    assert captured["redirect_uri"] == ["http://localhost:9999"]
    assert captured["client_id"] == ["the-id"]
    assert captured["scope"] == ["fspt-r"]
    assert captured["response_type"] == ["code"]


# ── failures ────────────────────────────────────────────────────────────


def test_a_refused_exchange_raises_rather_than_saving_nothing(
    monkeypatch: pytest.MonkeyPatch, saved: list[Any], authorised: None
) -> None:
    """Persisting a half-token would look authorised and fail on first use."""
    monkeypatch.setattr(oauth.requests, "post", lambda *a, **k: FakeResponse({"error": "invalid_grant"}, status=400))

    with pytest.raises(YahooLoginRequiredError):
        oauth.authorise("id", "secret", REDIRECT)

    assert saved == []


def test_the_token_is_persisted_in_the_shape_the_client_reads(
    posted: list[Any], saved: list[tuple[str, dict[str, Any]]], authorised: None
) -> None:
    """Only the handshake changed; the vendor Context still loads this file."""
    oauth.authorise("id", "secret", REDIRECT)

    key, value = saved[0]
    assert key == "auth"
    assert set(value) == {"client_id", "client_secret", "access_token", "access_token_expires", "refresh_token"}
    assert value["access_token"] == "at"
    assert value["refresh_token"] == "rt"


def test_an_expiry_is_stored_as_an_absolute_time(
    posted: list[Any], saved: list[tuple[str, dict[str, Any]]], authorised: None
) -> None:
    """`expires_in` is a duration; storing it raw would read as 1970."""
    import time

    oauth.authorise("id", "secret", REDIRECT)

    assert saved[0][1]["access_token_expires"] > time.time()
