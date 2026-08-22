"""Tests for the pure logic in NBAClient — no network, no cache file on disk."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from the_front_office.clients.nba.client import PACIFIC, NBAClient
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


def _schedule_client(games: list[dict[str, object]]) -> NBAClient:
    c = _client()
    c._cache_data["schedule"] = {
        "teams": {"LAL": games},  # type: ignore[typeddict-item]
        "updated_at": datetime.now().isoformat(),
    }
    c._ensure_schedule_loaded = lambda: None  # type: ignore[method-assign]
    return c


def test_counts_only_future_scheduled_games() -> None:
    today = date.today()
    c = _schedule_client(
        [
            {"date": (today + timedelta(days=1)).isoformat(), "status": 1, "home": "LAL", "away": "BOS"},
            {"date": (today + timedelta(days=2)).isoformat(), "status": 2, "home": "LAL", "away": "NYK"},
            {"date": (today + timedelta(days=3)).isoformat(), "status": 3, "home": "LAL", "away": "PHX"},
            {"date": (today - timedelta(days=1)).isoformat(), "status": 1, "home": "LAL", "away": "MIA"},
        ]
    )
    # status 1 (scheduled) and 2 (live) count; 3 (final) and past dates do not.
    assert c.get_remaining_games("LAL", today, today + timedelta(days=7)) == 2


def test_games_outside_the_matchup_window_are_excluded() -> None:
    today = date.today()
    c = _schedule_client(
        [
            {"date": (today + timedelta(days=10)).isoformat(), "status": 1, "home": "LAL", "away": "BOS"},
        ]
    )
    assert c.get_remaining_games("LAL", today, today + timedelta(days=7)) == 0


def test_team_abbreviation_is_case_insensitive() -> None:
    today = date.today()
    c = _schedule_client(
        [
            {"date": (today + timedelta(days=1)).isoformat(), "status": 1, "home": "LAL", "away": "BOS"},
        ]
    )
    assert c.get_remaining_games("lal", today, today + timedelta(days=7)) == 1


def test_unknown_team_returns_zero() -> None:
    today = date.today()
    c = _schedule_client([])
    assert c.get_remaining_games("XXX", today, today + timedelta(days=7)) == 0
