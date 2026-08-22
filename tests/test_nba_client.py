"""Tests for the pure logic in NBAClient — no network, no cache file on disk."""

from datetime import date, datetime, timedelta

import pytest

from the_front_office.clients.nba.client import NBAClient
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


def test_empty_cache_is_stale() -> None:
    assert _client()._is_league_gamelog_stale() is True


def test_unparseable_timestamp_is_stale() -> None:
    c = _client()
    c._cache_data["league_gamelog"]["updated_at"] = "not-a-timestamp"
    assert c._is_league_gamelog_stale() is True


def test_yesterdays_cache_is_stale() -> None:
    c = _client()
    c._cache_data["league_gamelog"]["updated_at"] = (datetime.now() - timedelta(days=1)).isoformat()
    assert c._is_league_gamelog_stale() is True


def test_cache_written_seconds_ago_is_fresh() -> None:
    """No 1AM/3PM boundary can fall between a moment ago and now."""
    c = _client()
    c._cache_data["league_gamelog"]["updated_at"] = (datetime.now() - timedelta(seconds=5)).isoformat()
    assert c._is_league_gamelog_stale() is False


def test_crossing_the_3pm_boundary_invalidates() -> None:
    """Written at 14:00, checked at 15:30 — the 15:00 boundary was crossed."""
    c = _client()
    today = date.today()
    c._cache_data["league_gamelog"]["updated_at"] = (
        datetime.combine(today, datetime.min.time()).replace(hour=14).isoformat()
    )

    now = datetime.combine(today, datetime.min.time()).replace(hour=15, minute=30)
    assert _stale_at(c, now) is True


def test_same_side_of_a_boundary_stays_fresh() -> None:
    """Written at 16:00, checked at 17:00 — no boundary in between."""
    c = _client()
    today = date.today()
    c._cache_data["league_gamelog"]["updated_at"] = (
        datetime.combine(today, datetime.min.time()).replace(hour=16).isoformat()
    )

    now = datetime.combine(today, datetime.min.time()).replace(hour=17)
    assert _stale_at(c, now) is False


def _stale_at(client: NBAClient, now: datetime) -> bool:
    """Evaluate staleness as if `now` were the current time."""
    import the_front_office.clients.nba.client as mod

    real = mod.datetime

    class FrozenDatetime(real):  # type: ignore[misc, valid-type]
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return now

    mod.datetime = FrozenDatetime  # type: ignore[misc]
    try:
        return client._is_league_gamelog_stale()
    finally:
        mod.datetime = real  # type: ignore[misc]


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
