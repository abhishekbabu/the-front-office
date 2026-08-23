"""One JSON cache on disk, shared by every platform this app reads from.

The platforms differ in transport — two are plain public JSON, one is behind a
vendor SDK, one is a stats endpoint that rate-limits aggressively — but they
want the same thing from a cache: keep the last answer, and say when it stopped
being true. So the store is shared and only the *freshness rule* varies.

Most rules are a TTL, chosen from how fast the endpoint actually moves: Sleeper
asks callers to fetch its ~14MB catalog at most once a day, and a finished
season never changes again. Some are not expressible as a duration at all —
basketball's game log is good until the next game tips off, which is a moment
rather than an interval — so a rule is a predicate over when the entry was
stored, and `within` is the common case of one.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

Freshness = Callable[[datetime, datetime], bool]
"""Given when an entry was stored and what time it is now, is it still good?"""


def within(ttl: timedelta) -> Freshness:
    """The common rule: good for a fixed interval after it was stored."""
    return lambda stored_at, now: now - stored_at <= ttl


def _rule(freshness: timedelta | Freshness) -> Freshness:
    """Accept a bare TTL wherever a rule is asked for, since most are one."""
    return within(freshness) if isinstance(freshness, timedelta) else freshness


class JsonDiskCache:
    """Namespaced JSON values on disk, each with its own TTL."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
        except (OSError, ValueError) as e:
            logger.warning(f"Discarding unreadable cache {self._path}: {e}")
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError as e:
            # Best effort: a cache we cannot persist still works for this run.
            logger.warning(f"Could not write cache {self._path}: {e}")

    def get(self, key: str, freshness: timedelta | Freshness, now: datetime | None = None) -> Any | None:
        """Return the cached value for `key`, or None if absent or stale.

        `freshness` is a TTL for the usual case, or a predicate for a rule a
        duration cannot express.
        """
        entry = self._data.get(key)
        if not entry or "stored_at" not in entry:
            return None
        try:
            stored_at = datetime.fromisoformat(entry["stored_at"])
        except ValueError:
            return None
        if stored_at.tzinfo is None:
            return None  # no zone, so it cannot be placed on a timeline
        moment = now or datetime.now(timezone.utc)
        if not _rule(freshness)(stored_at, moment):
            return None
        return entry.get("value")

    def set(self, key: str, value: Any, now: datetime | None = None) -> None:
        """Store `value` under `key` and persist."""
        stored_at = (now or datetime.now(timezone.utc)).isoformat()
        self._data[key] = {"stored_at": stored_at, "value": value}
        self._save()

    def cached(
        self,
        key: str,
        freshness: timedelta | Freshness,
        fetch: Callable[[], T],
        now: datetime | None = None,
    ) -> T:
        """The stored value for `key`, calling `fetch` only when it is stale.

        The read-through every platform wants, in one place: a hit never
        touches the network, and a miss stores what it fetched. A fetch that
        raises propagates rather than caching a failure as though it were an
        answer.
        """
        hit = self.get(key, freshness, now=now)
        if hit is not None:
            return hit
        value = fetch()
        self.set(key, value, now=now)
        return value

    def clear(self) -> None:
        self._data = {}
        self._save()
