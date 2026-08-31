"""Cached, retried access to a public JSON API.

Sleeper and the Fantasy Premier League game are both open and read-only: no
OAuth, no key, plain GETs whose only real obligations are politeness about
request volume and a second attempt when a connection stalls. That is the whole
of what they share, so it is a collaborator a client holds rather than a base
class it inherits — the Yahoo client reaches its platform through
vendor SDKs and would have no transport to inherit.

Each caller supplies its own retry policy and its own domain error, because
those are the two things that genuinely differ: Sleeper documents 429 as its
rate-limit signal, and a failure has to surface as the error the sport's
adapter already raises.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import requests
from tenacity import Retrying

from thefrontoffice.adapters.outbound.platforms.cache import Freshness, JsonDiskCache
from thefrontoffice.domain.errors import FrontOfficeError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30
# Enough to collapse a season of weekly requests into one wait, well inside
# what these platforms ask for — Sleeper documents 1000 a minute.
MAX_PARALLEL_REQUESTS = 8


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

    def cached_many(self, urls: dict[str, str], freshness: timedelta | Freshness) -> dict[str, Any]:
        """Several cached GETs at once, fetching only the misses and in parallel.

        A season of weekly matchups is eighteen independent requests, and run
        one after another they are most of the wait on a page that is otherwise
        instant. Only the HTTP is concurrent: the cache file is read-modify-
        written whole, so the writes stay on this thread or they clobber each
        other — the same split the Yahoo client needs for the same reason.

        A request that fails leaves its key out rather than failing the batch.
        Seventeen weeks of a season is a season with a hole in it, which is
        worth more than no season at all.
        """
        hits = {key: self._cache.get(key, freshness) for key in urls}
        misses = {key: urls[key] for key, hit in hits.items() if hit is None}
        if not misses:
            return hits

        fetched: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=min(len(misses), MAX_PARALLEL_REQUESTS)) as pool:
            futures = {pool.submit(self.get, url): key for key, url in misses.items()}
            for future in futures:
                key = futures[future]
                try:
                    fetched[key] = future.result()
                except FrontOfficeError as e:
                    logger.warning(f"{self._name} batch missing {key}: {e}")

        # Serial: one writer, so the cache file cannot be clobbered.
        for key, value in fetched.items():
            self._cache.set(key, value)
        return {**{k: v for k, v in hits.items() if v is not None}, **fetched}

    def cache_get(self, key: str, freshness: timedelta | Freshness) -> Any:
        """A cache read without a fetch, for a caller that transforms before storing."""
        return self._cache.get(key, freshness)

    def cache_set(self, key: str, value: Any) -> None:
        self._cache.set(key, value)
