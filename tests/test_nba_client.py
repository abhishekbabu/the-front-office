"""Tests for the pure logic in NBAClient — no network, no cache file on disk."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from the_front_office.clients.nba.client import PACIFIC, NBAClient, _parse_timestamp, _utc_now
from the_front_office.clients.nba.types import GameLogRecord


def _client() -> NBAClient:
    """An NBAClient with the cache pre-seeded, bypassing __init__'s disk read."""
    c = NBAClient.__new__(NBAClient)
    c._last_call_time = 0.0
    c._cache_data = {
        "league_gamelog": {"games": {}, "updated_at": ""},
        "schedule": {"teams": {}, "updated_at": ""},
    }
    return c


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


# ── _extract_9cat_from_records ──────────────────────────────────────────


def test_percentages_use_totals_not_average_of_ratios() -> None:
    """FG% must be sum(FGM)/sum(FGA), not the mean of per-game percentages.

    The two disagree whenever attempts vary between games, which is the whole
    reason this is computed by hand instead of averaged.
    """
    records = [
        _game(FGM=1.0, FGA=1.0),  # 100% on 1 attempt
        _game(FGM=0.0, FGA=19.0),  # 0% on 19 attempts
    ]
    stats = _client()._extract_9cat_from_records(records)

    assert stats["FG_PCT"] == 0.05  # 1/20 — the correct volume-weighted value
    assert stats["FG_PCT"] != pytest.approx(0.5)  # what averaging the ratios would give


def test_counting_stats_are_per_game_averages() -> None:
    records = [_game(PTS=10.0), _game(PTS=20.0), _game(PTS=30.0)]
    stats = _client()._extract_9cat_from_records(records)
    assert stats["PTS"] == 20.0


def test_zero_attempts_does_not_divide_by_zero() -> None:
    records = [_game(FGM=0.0, FGA=0.0, FTM=0.0, FTA=0.0)]
    stats = _client()._extract_9cat_from_records(records)
    assert stats["FG_PCT"] == 0.0
    assert stats["FT_PCT"] == 0.0


# ── _is_league_gamelog_stale ────────────────────────────────────────────


def _pt(y: int, m: int, d: int, hour: int, minute: int = 0) -> datetime:
    """A Pacific-time wall clock instant."""
    return datetime(y, m, d, hour, minute, tzinfo=PACIFIC)


def _with_updated_at(ts: datetime | str) -> NBAClient:
    c = _client()
    c._cache_data["league_gamelog"]["updated_at"] = ts if isinstance(ts, str) else ts.isoformat()
    return c


def test_empty_cache_is_stale() -> None:
    assert _client()._is_league_gamelog_stale() is True


def test_unparseable_timestamp_is_stale() -> None:
    assert _with_updated_at("not-a-timestamp")._is_league_gamelog_stale() is True


def test_legacy_naive_timestamp_is_stale() -> None:
    """Pre-fix caches stored a local-clock reading with no zone, so it cannot be
    placed on a timeline. One refetch on upgrade, then self-healing."""
    c = _with_updated_at("2026-02-09T14:00:00")
    assert c._is_league_gamelog_stale(now=_pt(2026, 2, 9, 14, 5)) is True


def test_previous_pacific_day_is_stale() -> None:
    c = _with_updated_at(_pt(2026, 2, 8, 20))
    assert c._is_league_gamelog_stale(now=_pt(2026, 2, 9, 10)) is True


def test_crossing_the_3pm_pacific_boundary_invalidates() -> None:
    c = _with_updated_at(_pt(2026, 2, 9, 14))
    assert c._is_league_gamelog_stale(now=_pt(2026, 2, 9, 15, 30)) is True


def test_same_side_of_a_boundary_stays_fresh() -> None:
    c = _with_updated_at(_pt(2026, 2, 9, 16))
    assert c._is_league_gamelog_stale(now=_pt(2026, 2, 9, 17)) is False


def test_boundaries_are_pacific_regardless_of_local_zone() -> None:
    """The regression this fix exists for.

    Written 14:00 PT, checked 14:30 PT — no boundary crossed, so the cache is
    fresh. Expressing the identical instants in Eastern must not change that;
    the old code compared a naive local clock against the PT boundary, so on an
    ET machine 17:00/17:30 local straddled the 15:00 boundary and forced a
    refetch that never should have happened (and, in the other direction, let
    the pre-tip-off refresh fire three hours late).
    """
    eastern = ZoneInfo("America/New_York")
    written_pt = _pt(2026, 2, 9, 14)
    checked_pt = _pt(2026, 2, 9, 14, 30)

    c = _with_updated_at(written_pt.astimezone(eastern))
    assert c._is_league_gamelog_stale(now=checked_pt.astimezone(eastern)) is False
    # And identical to the PT-expressed answer.
    assert c._is_league_gamelog_stale(now=checked_pt) is False


def test_utc_stored_timestamp_is_interpreted_in_pacific() -> None:
    """Timestamps are written as UTC; the boundary check must convert."""
    # 2026-02-09 22:00 UTC == 14:00 PST. Checking at 23:30 UTC == 15:30 PST
    # crosses the 15:00 PT boundary.
    c = _with_updated_at(datetime(2026, 2, 9, 22, 0, tzinfo=timezone.utc))
    now = datetime(2026, 2, 9, 23, 30, tzinfo=timezone.utc)
    assert c._is_league_gamelog_stale(now=now) is True


def test_schedule_age_is_computed_across_zones() -> None:
    c = _client()
    c._cache_data["schedule"]["updated_at"] = datetime(2026, 2, 9, 12, 0, tzinfo=timezone.utc).isoformat()
    now = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
    assert c._get_schedule_age_hours(now=now) == pytest.approx(24.0)


def test_undateable_schedule_reports_max_age() -> None:
    assert _client()._get_schedule_age_hours() == 999.0
    c = _client()
    c._cache_data["schedule"]["updated_at"] = "2026-02-09T12:00:00"  # naive, legacy
    assert c._get_schedule_age_hours() == 999.0


# ── get_remaining_games ─────────────────────────────────────────────────


def _sched_game(day: str, tipoff_utc: str, status: int = 1) -> dict[str, object]:
    return {"date": day, "tipoff_utc": tipoff_utc, "status": status, "home": "LAL", "away": "BOS"}


def _schedule_client(games: list[dict[str, object]]) -> NBAClient:
    c = _client()
    c._cache_data["schedule"] = {
        "teams": {"LAL": games},  # type: ignore[typeddict-item]
        "updated_at": _utc_now().isoformat(),
    }
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
    """The regression this fix exists for.

    21:30 PT on Feb 10 is already 00:30 ET on Feb 11. The old code compared the
    game's date label against a local `date.today()`, so on an Eastern machine
    the date had rolled over and a game tipping at 22:00 PT that night was
    dropped from the count. The instant is the same either way, so the answer
    must be too.
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
    """Regression: datetime.fromisoformat only accepts "Z" from 3.11, and this
    project targets 3.10. Every gameDateTimeUTC the NBA returns ends in Z, so
    without normalisation every game parsed as None and every team reported
    zero remaining games."""
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
    c._cache_data["schedule"]["teams"]["BOS"] = [  # type: ignore[typeddict-item]
        _sched_game("2026-02-12", "2026-02-13T03:00:00Z")
    ]
    assert c.get_remaining_games_bulk(["LAL", "bos"], WINDOW_START, WINDOW_END, now=now) == {
        "LAL": 1,
        "BOS": 1,
    }


# ── schedule cache migration ────────────────────────────────────────────


def test_schedule_written_before_tipoff_field_is_refetched() -> None:
    c = _client()
    c._cache_data["schedule"] = {
        "teams": {"LAL": [{"date": "2026-02-10", "status": 1, "home": "LAL", "away": "BOS"}]},  # type: ignore[typeddict-item]
        "updated_at": _utc_now().isoformat(),
    }
    assert c._schedule_predates_tipoff_field() is True


def test_current_shape_is_not_refetched() -> None:
    c = _schedule_client([_sched_game("2026-02-12", "2026-02-13T03:00:00Z")])
    assert c._schedule_predates_tipoff_field() is False


def test_empty_schedule_is_not_treated_as_outdated_shape() -> None:
    assert _client()._schedule_predates_tipoff_field() is False
