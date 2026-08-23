"""Tests for the shared JSON disk cache.

The store every platform reads through, so both halves matter: what it keeps,
and the freshness rules that decide when what it kept stopped being true.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from the_front_office.adapters.outbound.platforms.cache import JsonDiskCache, within

HOUR = timedelta(hours=1)
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_value_round_trips(tmp_path: Path) -> None:
    c = JsonDiskCache(tmp_path / "c.json")
    c.set("k", {"a": 1}, now=T0)
    assert c.get("k", HOUR, now=T0) == {"a": 1}


def test_value_persists_across_instances(tmp_path: Path) -> None:
    JsonDiskCache(tmp_path / "c.json").set("k", [1, 2], now=T0)
    assert JsonDiskCache(tmp_path / "c.json").get("k", HOUR, now=T0) == [1, 2]


def test_missing_key_is_none(tmp_path: Path) -> None:
    assert JsonDiskCache(tmp_path / "c.json").get("nope", HOUR) is None


def test_expired_value_is_none(tmp_path: Path) -> None:
    c = JsonDiskCache(tmp_path / "c.json")
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0 + timedelta(minutes=59)) == "v"
    assert c.get("k", HOUR, now=T0 + timedelta(hours=1, seconds=1)) is None


def test_each_key_has_its_own_ttl(tmp_path: Path) -> None:
    """Projections and live matchup scores go stale at very different rates."""
    c = JsonDiskCache(tmp_path / "c.json")
    c.set("slow", "v", now=T0)
    c.set("fast", "v", now=T0)
    later = T0 + timedelta(minutes=30)
    assert c.get("slow", timedelta(hours=6), now=later) == "v"
    assert c.get("fast", timedelta(minutes=2), now=later) is None


def test_corrupt_file_is_discarded_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text("{not json", encoding="utf-8")
    c = JsonDiskCache(path)
    assert c.get("k", HOUR) is None
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0) == "v"


def test_non_dict_file_is_discarded(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert JsonDiskCache(path).get("k", HOUR) is None


def test_naive_timestamp_is_treated_as_unusable(tmp_path: Path) -> None:
    """Without a zone the entry cannot be placed on a timeline."""
    import json

    path = tmp_path / "c.json"
    path.write_text(json.dumps({"k": {"stored_at": "2026-09-01T12:00:00", "value": "v"}}), encoding="utf-8")
    assert JsonDiskCache(path).get("k", HOUR, now=T0) is None


def test_unparseable_timestamp_is_treated_as_unusable(tmp_path: Path) -> None:
    import json

    path = tmp_path / "c.json"
    path.write_text(json.dumps({"k": {"stored_at": "whenever", "value": "v"}}), encoding="utf-8")
    assert JsonDiskCache(path).get("k", HOUR, now=T0) is None


def test_unwritable_path_does_not_raise(tmp_path: Path) -> None:
    """A cache we cannot persist still has to work for this run."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    c = JsonDiskCache(blocker / "sub" / "c.json")
    c.set("k", "v", now=T0)
    assert c.get("k", HOUR, now=T0) == "v"


def test_clear_empties_the_cache(tmp_path: Path) -> None:
    c = JsonDiskCache(tmp_path / "c.json")
    c.set("k", "v", now=T0)
    c.clear()
    assert c.get("k", HOUR, now=T0) is None


# ── freshness rules ─────────────────────────────────────────────────────


def test_a_ttl_is_the_common_rule(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "c.json")
    stored = datetime(2026, 2, 9, 12, tzinfo=timezone.utc)
    cache.set("k", "v", now=stored)

    assert cache.get("k", timedelta(hours=2), now=stored + timedelta(hours=1)) == "v"
    assert cache.get("k", timedelta(hours=2), now=stored + timedelta(hours=3)) is None


def test_a_rule_a_duration_cannot_express(tmp_path: Path) -> None:
    """The reason freshness is a predicate: basketball's gamelog is good until
    the next boundary passes, which is a moment rather than an interval."""
    cache = JsonDiskCache(tmp_path / "c.json")
    stored = datetime(2026, 2, 9, 12, tzinfo=timezone.utc)
    cache.set("k", "v", now=stored)

    # Good only while stored and now fall on the same calendar day.
    def same_day(at: datetime, now: datetime) -> bool:
        return at.date() == now.date()

    assert cache.get("k", same_day, now=stored + timedelta(hours=6)) == "v"
    assert cache.get("k", same_day, now=stored + timedelta(hours=13)) is None


def test_within_is_a_ttl_as_a_rule(tmp_path: Path) -> None:
    """So a caller can hold one and a caller can hold the other."""
    cache = JsonDiskCache(tmp_path / "c.json")
    stored = datetime(2026, 2, 9, 12, tzinfo=timezone.utc)
    cache.set("k", "v", now=stored)

    rule = within(timedelta(minutes=30))
    assert cache.get("k", rule, now=stored + timedelta(minutes=10)) == "v"
    assert cache.get("k", rule, now=stored + timedelta(minutes=40)) is None


# ── read-through ────────────────────────────────────────────────────────


def test_a_hit_never_calls_the_fetch(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "c.json")
    cache.set("k", "stored")
    calls: list[int] = []

    def _fetch() -> str:
        calls.append(1)
        return "fetched"

    value = cache.cached("k", timedelta(hours=1), _fetch)

    assert value == "stored"
    assert calls == []


def test_a_miss_fetches_and_stores(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path / "c.json")

    assert cache.cached("k", timedelta(hours=1), lambda: "fetched") == "fetched"
    assert cache.get("k", timedelta(hours=1)) == "fetched"


def test_a_failed_fetch_is_not_cached_as_though_it_were_an_answer(tmp_path: Path) -> None:
    """Otherwise the next caller reads the outage back as data."""
    cache = JsonDiskCache(tmp_path / "c.json")

    def _boom() -> str:
        raise RuntimeError("platform down")

    with pytest.raises(RuntimeError):
        cache.cached("k", timedelta(hours=1), _boom)

    assert cache.get("k", timedelta(hours=1)) is None
