"""Retry policy shared by the platform clients.

Every platform this app talks to fails the same two ways — the connection
stalls, or the server returns a 5xx — and each has its own extra signal for
"come back later". Encoding the common part once means a client only declares
what is unusual about it.

The distinction that matters is transient versus permanent: retrying a 404 or a
changed payload shape burns a rate-limit budget on a request that will fail
identically.
"""

import logging
from collections.abc import Callable

import requests
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


def is_transient(exc: BaseException, retryable_status: frozenset[int] = frozenset()) -> bool:
    """Whether a failure is worth a second attempt.

    Args:
        retryable_status: extra HTTP codes to retry beyond 5xx, such as a
            platform's documented rate-limit code.
    """
    if isinstance(exc, RETRYABLE_NETWORK_EXCEPTIONS):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code >= 500 or response.status_code in retryable_status
    return False


def build_retry(
    *,
    attempts: int,
    multiplier: float,
    min_wait: float,
    max_wait: float,
    predicate: Callable[[BaseException], bool],
) -> Retrying:
    """A tenacity retry with exponential backoff, logging each pause.

    `reraise=True` so callers see the original error rather than tenacity's
    wrapper, and can translate it into a domain error.
    """
    return Retrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
        retry=retry_if_exception(predicate),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
