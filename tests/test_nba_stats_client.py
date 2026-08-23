"""Tests for the pure logic in NBAStatsClient — no network, no cache file on disk."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from the_front_office.adapters.outbound.platforms.cache import JsonDiskCache
from the_front_office.adapters.outbound.platforms.nba_stats.client import (
    GAMELOG_KEY,
    PACIFIC,
    SCHEDULE_KEY,
    SCHEDULE_TTL,
    NBAStatsClient,
    _parse_timestamp,
)
from the_front_office.adapters.outbound.platforms.nba_stats.stats import extract_nine_cat
from the_front_office.adapters.outbound.platforms.nba_stats.types import GameLogRecord


class MemoryCache(JsonDiskCache):
    """The real cache with its disk I/O removed.

    The store's own expiry is what a freshness rule means, so the tests below
    exercise it rather than a stand-in that could disagree with it.
    """

    def __init__(self) -> None:
        self._path = Path("unused")
        self._data = {}

    def _load(self) -> None:
        return None

    def _save(self) -> None:
        return None


def _client() -> NBAStatsClient:
    """An NBAStatsClient whose cache never touches disk."""
    return NBAStatsClient(cache=MemoryCache())


def _game(**overrides: float | str) -> GameLogRecord:
    base: dict[str, float | str] = {
        "GAME_DATE": "2026-01-01",
        "PTS": 10.0,
        "REB": 5.0,
        "AST": 3.0,
        "STL": 1.0,
        "BLK": 1.0,
        "TOV": 2.0,
        "FG3M": 2.0,
        "FGA": 10.0,
        "FGM": 5.0,
        "FTA": 4.0,
        "FTM": 3.0,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


# ── extract_nine_cat ────────────────────────────────────────────────────


def test_percentages_use_totals_not_average_of_ratios() -> None:
    """FG% must be sum(FGM)/sum(FGA), not the mean of per-game percentages.

    The two disagree whenever attempts vary between games, which is the whole
    reason this is computed by hand instead of averaged.
    """
    records = [
        _game(FGM=1.0, FGA=1.0),  # 100% on 1 attempt
        _game(FGM=0.0, FGA=19.0),  # 0% on 19 attempts
    ]
    stats = extract_nine_cat(records)

    assert stats["FG_PCT"] == 0.05  # 1/20 — the correct volume-weighted value
    assert stats["FG_PCT"] != pytest.approx(0.5)  # what averaging the ratios would give


def test_counting_stats_are_per_game_averages() -> None:
    records = [_game(PTS=10.0), _game(PTS=20.0), _game(PTS=30.0)]
    stats = extract_nine_cat(records)
    assert stats["PTS"] == 20.0


def test_zero_attempts_does_not_divide_by_zero() -> None:
    records = [_game(FGM=0.0, FGA=0.0, FTM=0.0, FTA=0.0)]
    stats = extract_nine_cat(records)
    assert stats["FG_PCT"] == 0.0
    assert stats["FT_PCT"] == 0.0


# ── _is_league_gamelog_stale ────────────────────────────────────────────


def _pt(y: int, m: int, d: int, hour: int, minute: int = 0) -> datetime:
    """A Pacific-time wall clock instant."""
    return datetime(y, m, d, hour, minute, tzinfo=PACIFIC)


def _stored(ts: datetime) -> NBAStatsClient:
    """A client whose gamelog was cached at `ts`."""
    c = _client()
    c._cache.set(GAMELOG_KEY, {"A B": []}, now=ts)
    return c


def _fresh(c: NBAStatsClient, now: datetime) -> bool:
    """Whether the cache would answer, which is the rule under test."""
    return c._cache.get(GAMELOG_KEY, c._gamelog_is_fresh, now=now) is not None


def test_an_empty_cache_has_nothing_to_answer_with() -> None:
    assert _fresh(_client(), _pt(2026, 2, 9, 10)) is False


def test_an_undateable_entry_is_stale() -> None:
    """A value with no readable timestamp cannot be placed on a timeline, so it
    cannot be shown to be fresh. One refetch, then self-healing."""
    c = _client()
    c._cache._data[GAMELOG_KEY] = {"stored_at": "not-a-timestamp", "value": {}}
    assert _fresh(c, _pt(2026, 2, 9, 14, 5)) is False


def test_a_legacy_naive_timestamp_is_stale() -> None:
    """Pre-fix caches stored a local-clock reading with no zone."""
    c = _client()
    c._cache._data[GAMELOG_KEY] = {"stored_at": "2026-02-09T14:00:00", "value": {}}
    assert _fresh(c, _pt(2026, 2, 9, 14, 5)) is False


def test_a_previous_pacific_day_is_stale() -> None:
    assert _fresh(_stored(_pt(2026, 2, 8, 20)), _pt(2026, 2, 9, 10)) is False


def test_crossing_the_3pm_pacific_boundary_invalidates() -> None:
    assert _fresh(_stored(_pt(2026, 2, 9, 14)), _pt(2026, 2, 9, 15, 30)) is False


def test_same_side_of_a_boundary_stays_fresh() -> None:
    assert _fresh(_stored(_pt(2026, 2, 9, 16)), _pt(2026, 2, 9, 17)) is True


def test_boundaries_are_pacific_regardless_of_local_zone() -> None:
    """Boundaries are Pacific, whatever zone the machine is in.

    Written 14:00 PT, checked 14:30 PT — no boundary crossed, so the cache is
    fresh. Expressing the identical instants in Eastern must not change that.
    """
    eastern = ZoneInfo("America/New_York")
    written_pt = _pt(2026, 2, 9, 14)
    checked_pt = _pt(2026, 2, 9, 14, 30)

    c = _stored(written_pt.astimezone(eastern))
    assert _fresh(c, checked_pt.astimezone(eastern)) is True
    # And identical to the PT-expressed answer.
    assert _fresh(c, checked_pt) is True


def test_a_utc_stored_timestamp_is_interpreted_in_pacific() -> None:
    """Timestamps are written as UTC; the boundary check must convert."""
    # 2026-02-09 22:00 UTC == 14:00 PST. Checking at 23:30 UTC == 15:30 PST
    # crosses the 15:00 PT boundary.
    c = _stored(datetime(2026, 2, 9, 22, 0, tzinfo=timezone.utc))
    now = datetime(2026, 2, 9, 23, 30, tzinfo=timezone.utc)
    assert _fresh(c, now) is False


def test_the_schedule_expires_on_a_plain_ttl() -> None:
    """Unlike the gamelog: a season's fixture list has no moment it turns."""
    c = _client()
    stored = datetime(2026, 2, 9, 12, 0, tzinfo=timezone.utc)
    c._cache.set(SCHEDULE_KEY, {"LAL": []}, now=stored)

    assert c._cache.get(SCHEDULE_KEY, SCHEDULE_TTL, now=stored + timedelta(hours=23)) is not None
    assert c._cache.get(SCHEDULE_KEY, SCHEDULE_TTL, now=stored + timedelta(hours=25)) is None


# ── get_remaining_games ─────────────────────────────────────────────────


def _sched_game(day: str, tipoff_utc: str, status: int = 1) -> dict[str, object]:
    return {"date": day, "tipoff_utc": tipoff_utc, "status": status, "home": "LAL", "away": "BOS"}


def _schedule_client(games: list[dict[str, object]]) -> NBAStatsClient:
    c = _client()
    c._schedule = {"LAL": games}  # type: ignore[assignment]
    c._ensure_schedule_loaded = lambda: None  # type: ignore[method-assign]
    return c


WINDOW_START = date(2026, 2, 9)
WINDOW_END = date(2026, 2, 15)


def test_counts_only_games_that_have_not_tipped_off() -> None:
    now = datetime(2026, 2, 10, 20, 0, tzinfo=timezone.utc)  # 12:00 PT Feb 10
    c = _schedule_client(
        [
            _sched_game("2026-02-10", "2026-02-11T03:00:00Z"),  # tips tonight — counts
            _sched_game("2026-02-12", "2026-02-13T03:00:00Z"),  # future — counts
            _sched_game("2026-02-09", "2026-02-10T03:00:00Z"),  # already tipped — does not
        ]
    )
    assert c.get_remaining_games("LAL", WINDOW_START, WINDOW_END, now=now) == 2


def test_finished_games_are_excluded_by_status() -> None:
    """A future-dated game marked final (postponed, rescheduled) must not count."""
    now = datetime(2026, 2, 10, 20, 0, tzinfo=timezone.utc)
    c = _schedule_client([_sched_game("2026-02-12", "2026-02-13T03:00:00Z", status=3)])
    assert c.get_remaining_games("LAL", WINDOW_START, WINDOW_END, now=now) == 0


def test_stale_cached_status_does_not_resurrect_a_played_sched_game() -> None:
    """The schedule cache lives up to 24h, so a played game can still read
    status=1. The tip-off check is what actually excludes it."""
    now = datetime(2026, 2, 11, 6, 0, tzinfo=timezone.utc)
    c = _schedule_client([_sched_game("2026-02-10", "2026-02-11T03:00:00Z", status=1)])
    assert c.get_remaining_games("LAL", WINDOW_START, WINDOW_END, now=now) == 0


def test_result_does_not_depend_on_the_machines_timezone() -> None:
    """The count is the same in every machine timezone.

    21:30 PT on Feb 10 is already 00:30 ET on Feb 11, and a game tipping at
    22:00 PT that night still counts. The instant is the same in every zone, so
    the answer must be too.
    """
    tonight = _sched_game("2026-02-10", "2026-02-11T06:00:00Z")  # 22:00 PT Feb 10
    instant = datetime(2026, 2, 11, 5, 30, tzinfo=timezone.utc)  # 21:30 PT / 00:30 ET

    counts = {
        zone: _schedule_client([dict(tonight)]).get_remaining_games(
            "LAL", WINDOW_START, WINDOW_END, now=instant.astimezone(ZoneInfo(zone))
        )
        for zone in ("America/Los_Angeles", "America/New_York", "UTC", "Australia/Sydney")
    }
    assert set(counts.values()) == {1}, counts


def test_games_outside_the_matchup_window_are_excluded() -> None:
    now = datetime(2026, 2, 10, 20, 0, tzinfo=timezone.utc)
    c = _schedule_client([_sched_game("2026-02-20", "2026-02-21T03:00:00Z")])
    assert c.get_remaining_games("LAL", WINDOW_START, WINDOW_END, now=now) == 0


def test_window_bounds_are_inclusive() -> None:
    now = datetime(2026, 2, 8, 12, 0, tzinfo=timezone.utc)
    c = _schedule_client(
        [
            _sched_game("2026-02-09", "2026-02-10T03:00:00Z"),
            _sched_game("2026-02-15", "2026-02-16T03:00:00Z"),
        ]
    )
    assert c.get_remaining_games("LAL", WINDOW_START, WINDOW_END, now=now) == 2


def test_team_abbreviation_is_case_insensitive() -> None:
    now = datetime(2026, 2, 10, 20, 0, tzinfo=timezone.utc)
    c = _schedule_client([_sched_game("2026-02-12", "2026-02-13T03:00:00Z")])
    assert c.get_remaining_games("lal", WINDOW_START, WINDOW_END, now=now) == 1


def test_unknown_team_returns_zero() -> None:
    c = _schedule_client([])
    assert c.get_remaining_games("XXX", WINDOW_START, WINDOW_END) == 0


def test_z_suffixed_timestamps_parse_on_python_310() -> None:
    """fromisoformat accepts a trailing "Z" only from 3.11, and every
    gameDateTimeUTC the NBA returns has one."""
    parsed = _parse_timestamp("2026-02-13T03:00:00Z")
    assert parsed is not None
    assert parsed == datetime(2026, 2, 13, 3, 0, tzinfo=timezone.utc)
    # The +00:00 spelling must keep working too.
    assert _parse_timestamp("2026-02-13T03:00:00+00:00") == parsed


def test_unparseable_tipoff_is_skipped_not_counted() -> None:
    now = datetime(2026, 2, 10, 20, 0, tzinfo=timezone.utc)
    c = _schedule_client([_sched_game("2026-02-12", "not-a-timestamp")])
    assert c.get_remaining_games("LAL", WINDOW_START, WINDOW_END, now=now) == 0


def test_bulk_uses_one_instant_for_every_team() -> None:
    now = datetime(2026, 2, 10, 20, 0, tzinfo=timezone.utc)
    c = _schedule_client([_sched_game("2026-02-12", "2026-02-13T03:00:00Z")])
    c._schedule["BOS"] = [_sched_game("2026-02-12", "2026-02-13T03:00:00Z")]  # type: ignore[list-item]
    assert c.get_remaining_games_bulk(["LAL", "bos"], WINDOW_START, WINDOW_END, now=now) == {
        "LAL": 1,
        "BOS": 1,
    }


# ── schedule cache migration ────────────────────────────────────────────


def test_schedule_written_before_tipoff_field_is_refetched() -> None:
    """Age is not the only way an entry stops being usable: one written by an
    older version of this code is fresh and still unreadable."""
    teams = {"LAL": [{"date": "2026-02-10", "status": 1, "home": "LAL", "away": "BOS"}]}
    assert NBAStatsClient._predates_tipoff_field(teams) is True  # type: ignore[arg-type]


def test_current_shape_is_not_refetched() -> None:
    teams = {"LAL": [_sched_game("2026-02-12", "2026-02-13T03:00:00Z")]}
    assert NBAStatsClient._predates_tipoff_field(teams) is False  # type: ignore[arg-type]


def test_empty_schedule_is_not_treated_as_outdated_shape() -> None:
    assert NBAStatsClient._predates_tipoff_field({}) is False
