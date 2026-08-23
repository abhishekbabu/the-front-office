"""Cached, retried access to a public JSON API.

Sleeper and the Fantasy Premier League game are both open and read-only: no
OAuth, no key, plain GETs whose only real obligations are politeness about
request volume and a second attempt when a connection stalls. That is the whole
of what they share, so it is a collaborator a client holds rather than a base
class it inherits — the Yahoo and nba_api clients reach their platforms through
vendor SDKs and would have no transport to inherit.

Each caller supplies its own retry policy and its own domain error, because
those are the two things that genuinely differ: Sleeper documents 429 as its
rate-limit signal, and a failure has to surface as the error the sport's
adapter already raises.
"""

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import requests
from tenacity import Retrying

from the_front_office.adapters.outbound.platforms.cache import Freshness, JsonDiskCache
from the_front_office.domain.errors import FrontOfficeError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30


class JsonApiClient:
    """GETs against one public JSON API, retried and cached on disk."""

    def __init__(
        self,
        *,
        name: str,
        cache: JsonDiskCache,
        retry: Callable[[], Retrying],
        error: type[FrontOfficeError],
        session: Any = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """
        Args:
            name: the platform, for log lines and error messages.
            retry: builds a fresh policy per call; tenacity's is stateful.
            error: the domain error a failed request is translated into.
        """
        self._name = name
        self._cache = cache
        self._retry = retry
        self._error = error
        self._session = session or requests.Session()
        self._timeout = timeout

    def get(self, url: str, timeout: int | None = None) -> Any:
        """One GET, retried on transient failures, raising a domain error otherwise."""

        def _request() -> Any:
            response = self._session.get(url, timeout=timeout or self._timeout)
            response.raise_for_status()
            return response.json()

        try:
            return self._retry()(_request)
        except Exception as e:
            logger.error(f"{self._name} request failed ({url}): {e}")
            raise self._error(f"{self._name} request failed: {e}") from e

    def cached(self, key: str, url: str, freshness: timedelta | Freshness, timeout: int | None = None) -> Any:
        """The cached value for `key`, fetching and storing it when stale or absent."""
        return self._cache.cached(key, freshness, lambda: self.get(url, timeout=timeout))

    def cache_get(self, key: str, freshness: timedelta | Freshness) -> Any:
        """A cache read without a fetch, for a caller that transforms before storing."""
        return self._cache.get(key, freshness)

    def cache_set(self, key: str, value: Any) -> None:
        self._cache.set(key, value)
