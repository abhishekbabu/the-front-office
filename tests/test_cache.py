"""Tests for the TTL'd JSON disk cache."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from the_front_office.adapters.outbound.platforms.cache import JsonDiskCache

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
