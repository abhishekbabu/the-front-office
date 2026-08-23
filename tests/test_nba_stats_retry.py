"""Tests for which nba_api failures are treated as transient."""

import pytest
import requests

from the_front_office.adapters.outbound.platforms.nba_stats.client import (
    RETRY_MAX_ATTEMPTS,
    _is_nba_retryable_error,
    _nba_retry,
)


def _http_error(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(response=response)


# ── classification ──────────────────────────────────────────────────────


def test_network_failures_are_retryable() -> None:
    """stats.nba.com throttles by stalling, so timeouts dominate real failures."""
    assert _is_nba_retryable_error(requests.exceptions.Timeout())
    assert _is_nba_retryable_error(requests.exceptions.ConnectTimeout())
    assert _is_nba_retryable_error(requests.exceptions.ReadTimeout())
    assert _is_nba_retryable_error(requests.exceptions.ConnectionError())
    assert _is_nba_retryable_error(requests.exceptions.ChunkedEncodingError())


def test_server_errors_are_retryable() -> None:
    assert _is_nba_retryable_error(_http_error(500))
    assert _is_nba_retryable_error(_http_error(503))


def test_client_errors_are_not_retryable() -> None:
    """Retrying a 4xx just burns the rate-limit budget on an identical failure."""
    assert not _is_nba_retryable_error(_http_error(400))
    assert not _is_nba_retryable_error(_http_error(404))


def test_invalid_json_stub_is_retryable() -> None:
    """nba_api raises a bare Exception when a throttled response isn't JSON."""
    assert _is_nba_retryable_error(Exception("InvalidResponse: Response is not in a valid JSON format."))


def test_response_shape_changes_are_not_retryable() -> None:
    assert not _is_nba_retryable_error(KeyError("leagueSchedule"))
    assert not _is_nba_retryable_error(TypeError("not subscriptable"))
    assert not _is_nba_retryable_error(ValueError("bad literal"))


# ── retry behavior ─────────────────────────────────────────────────────


def test_transient_failure_then_success_is_retried() -> None:
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 2:
            raise requests.exceptions.Timeout()
        return "ok"

    retry = _nba_retry().copy(wait=lambda _: 0)  # no real sleeping in tests
    assert retry(flaky) == "ok"
    assert len(calls) == 2


def test_permanent_failure_is_not_retried() -> None:
    calls: list[int] = []

    def broken() -> str:
        calls.append(1)
        raise _http_error(404)

    retry = _nba_retry().copy(wait=lambda _: 0)
    with pytest.raises(requests.exceptions.HTTPError):
        retry(broken)
    assert len(calls) == 1, "a 404 must fail on the first attempt"


def test_retries_are_bounded_and_reraise() -> None:
    calls: list[int] = []

    def always_timeout() -> str:
        calls.append(1)
        raise requests.exceptions.Timeout()

    retry = _nba_retry().copy(wait=lambda _: 0)
    with pytest.raises(requests.exceptions.Timeout):
        retry(always_timeout)
    assert len(calls) == RETRY_MAX_ATTEMPTS
