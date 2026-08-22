"""A TTL'd JSON cache on disk, one entry per key.

Sleeper asks callers to stay under 1000 requests a minute and to fetch its ~14MB
player catalogue at most once a day, so caching here is politeness rather than
optimisation.

NBAClient uses its own cache instead: its invalidation is tied to when games
start and end, which a plain TTL cannot express.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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

    def get(self, key: str, ttl: timedelta, now: datetime | None = None) -> Any | None:
        """Return the cached value for `key`, or None if absent or expired."""
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
        if moment - stored_at > ttl:
            return None
        return entry.get("value")

    def set(self, key: str, value: Any, now: datetime | None = None) -> None:
        """Store `value` under `key` and persist."""
        stored_at = (now or datetime.now(timezone.utc)).isoformat()
        self._data[key] = {"stored_at": stored_at, "value": value}
        self._save()

    def clear(self) -> None:
        self._data = {}
        self._save()
