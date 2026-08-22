"""Tests for NBAClient's cache lifecycle and fetch orchestration.

The network calls are stubbed; what is exercised is the load/save round trip,
the staleness gates that decide whether to fetch at all, and the transform from
raw payload into cached records.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from the_front_office.clients.nba.client import NBAClient, _utc_now


def _client(tmp_path: Path) -> NBAClient:
    c = NBAClient.__new__(NBAClient)
    c._last_call_time = 0.0
    c._cache_file = tmp_path / ".nba_cache.json"
    c._cache_data = {
        "league_gamelog": {"games": {}, "updated_at": ""},
        "schedule": {"teams": {}, "updated_at": ""},
    }
    return c


GAMELOG_ROW = {
    "PLAYER_NAME": "A B",
    "GAME_DATE": "2026-01-05",
    "PTS": 20,
    "REB": 10,
    "AST": 5,
    "STL": 1,
    "BLK": 2,
    "TOV": 3,
    "FG3M": 2,
    "FGA": 15,
    "FGM": 8,
    "FTA": 4,
    "FTM": 3,
}

SCHEDULE_PAYLOAD: dict[str, Any] = {
    "leagueSchedule": {
        "gameDates": [
            {
                "games": [
                    {
                        "gameDateEst": "2026-02-10T00:00:00Z",
                        "gameDateTimeUTC": "2026-02-11T03:00:00Z",
                        "gameStatus": 1,
                        "homeTeam": {"teamTricode": "LAL"},
                        "awayTeam": {"teamTricode": "BOS"},
                    }
                ]
            }
        ]
    }
}


# ── cache I/O ───────────────────────────────────────────────────────────


def test_cache_round_trips_through_disk(tmp_path: Path) -> None:
    c = _client(tmp_path)
    c._cache_data["schedule"]["updated_at"] = _utc_now().isoformat()
    c._save_cache()

    reloaded = _client(tmp_path)
    reloaded._load_cache()
    assert reloaded._cache_data["schedule"]["updated_at"] == c._cache_data["schedule"]["updated_at"]


def test_missing_cache_file_is_not_an_error(tmp_path: Path) -> None:
    c = _client(tmp_path)
    c._load_cache()
    assert c._cache_data["league_gamelog"]["games"] == {}


def test_corrupt_cache_falls_back_to_empty(tmp_path: Path) -> None:
    """A truncated write must not stop the app from starting."""
    path = tmp_path / ".nba_cache.json"
    path.write_text("{not json", encoding="utf-8")
    c = _client(tmp_path)
    c._load_cache()
    assert c._cache_data["league_gamelog"]["games"] == {}


def test_save_failure_is_logged_not_raised(tmp_path: Path) -> None:
    c = _client(tmp_path)
    c._cache_file = tmp_path / "no-such-dir" / "cache.json"
    c._save_cache()  # must not raise


# ── gamelog fetch ───────────────────────────────────────────────────────


def test_gamelog_is_transformed_and_persisted(tmp_path: Path) -> None:
    c = _client(tmp_path)
    c._fetch_league_gamelog_frame = lambda: pd.DataFrame([GAMELOG_ROW])  # type: ignore[method-assign]
    c._ensure_league_gamelog_loaded()

    games = c._cache_data["league_gamelog"]["games"]
    assert list(games) == ["A B"]
    assert games["A B"][0]["PTS"] == 20.0
    assert isinstance(games["A B"][0]["GAME_DATE"], str)
    # and it survived the trip to disk
    assert "A B" in json.loads(c._cache_file.read_text(encoding="utf-8"))["league_gamelog"]["games"]


def test_fresh_gamelog_is_not_refetched(tmp_path: Path) -> None:
    c = _client(tmp_path)
    c._cache_data["league_gamelog"]["updated_at"] = _utc_now().isoformat()
    calls: list[int] = []

    def _fetch() -> pd.DataFrame:
        calls.append(1)
        return pd.DataFrame([GAMELOG_ROW])

    c._fetch_league_gamelog_frame = _fetch  # type: ignore[method-assign]
    c._ensure_league_gamelog_loaded()
    assert calls == []


def test_gamelog_fetch_failure_leaves_the_cache_usable(tmp_path: Path) -> None:
    """A failed refresh must degrade to stale data, not crash the report."""
    c = _client(tmp_path)

    def _boom() -> pd.DataFrame:
        raise RuntimeError("nba.com down")

    c._fetch_league_gamelog_frame = _boom  # type: ignore[method-assign]
    c._ensure_league_gamelog_loaded()  # must not raise
    assert c._cache_data["league_gamelog"]["games"] == {}


def test_multiple_games_accumulate_under_one_player(tmp_path: Path) -> None:
    c = _client(tmp_path)
    rows = [GAMELOG_ROW, {**GAMELOG_ROW, "GAME_DATE": "2026-01-07", "PTS": 30}]
    c._fetch_league_gamelog_frame = lambda: pd.DataFrame(rows)  # type: ignore[method-assign]
    c._ensure_league_gamelog_loaded()
    assert len(c._cache_data["league_gamelog"]["games"]["A B"]) == 2


# ── get_player_stats ────────────────────────────────────────────────────


def _seed_games(c: NBAClient, count: int) -> None:
    c._cache_data["league_gamelog"] = {
        "games": {"A B": [{**GAMELOG_ROW, "GAME_DATE": f"2026-01-{i + 1:02d}"} for i in range(count)]},  # type: ignore[dict-item]
        "updated_at": _utc_now().isoformat(),
    }


def test_only_windows_with_enough_games_are_reported(tmp_path: Path) -> None:
    c = _client(tmp_path)
    _seed_games(c, 7)
    stats = c.get_player_stats("A B")
    assert stats is not None
    assert "last_5" in stats
    assert "last_10" not in stats  # only 7 games played


def test_all_three_windows_appear_once_enough_games_exist(tmp_path: Path) -> None:
    c = _client(tmp_path)
    _seed_games(c, 20)
    stats = c.get_player_stats("A B")
    assert stats is not None
    assert set(stats) == {"last_5", "last_10", "last_15"}


def test_unknown_player_returns_none(tmp_path: Path) -> None:
    c = _client(tmp_path)
    _seed_games(c, 20)
    assert c.get_player_stats("Nobody At All") is None


def test_player_with_too_few_games_returns_none(tmp_path: Path) -> None:
    """Fewer than five games fills no window at all."""
    c = _client(tmp_path)
    _seed_games(c, 3)
    assert c.get_player_stats("A B") is None


# ── schedule fetch ──────────────────────────────────────────────────────


def test_schedule_is_indexed_by_both_teams(tmp_path: Path) -> None:
    c = _client(tmp_path)
    c._fetch_schedule_dict = lambda: SCHEDULE_PAYLOAD  # type: ignore[method-assign]
    c._ensure_schedule_loaded()
    teams = c._cache_data["schedule"]["teams"]
    assert set(teams) == {"LAL", "BOS"}
    assert teams["LAL"][0]["tipoff_utc"] == "2026-02-11T03:00:00Z"
    assert teams["LAL"][0]["date"] == "2026-02-10"


def test_fresh_schedule_is_not_refetched(tmp_path: Path) -> None:
    c = _client(tmp_path)
    c._fetch_schedule_dict = lambda: SCHEDULE_PAYLOAD  # type: ignore[method-assign]
    c._ensure_schedule_loaded()
    calls: list[int] = []

    def _fetch() -> dict[str, Any]:
        calls.append(1)
        return SCHEDULE_PAYLOAD

    c._fetch_schedule_dict = _fetch  # type: ignore[method-assign]
    c._ensure_schedule_loaded()
    assert calls == []


def test_schedule_fetch_failure_does_not_raise(tmp_path: Path) -> None:
    c = _client(tmp_path)

    def _boom() -> dict[str, Any]:
        raise RuntimeError("timeout")

    c._fetch_schedule_dict = _boom  # type: ignore[method-assign]
    c._ensure_schedule_loaded()
    assert c._cache_data["schedule"]["teams"] == {}


# ── rate limiting ───────────────────────────────────────────────────────


def test_calls_are_spaced_by_the_configured_delay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The project spec requires a delay between nba_api calls to avoid IP blocks."""
    import the_front_office.clients.nba.client as mod

    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(mod.time, "time", lambda: 100.0)

    c = _client(tmp_path)
    c._last_call_time = 99.0  # one second ago
    c._wait_for_rate_limit()

    assert slept and slept[0] == pytest.approx(mod.settings.nba_api_delay - 1.0)


def test_no_sleep_when_the_delay_has_already_elapsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import the_front_office.clients.nba.client as mod

    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(mod.time, "time", lambda: 1000.0)

    c = _client(tmp_path)
    c._last_call_time = 0.0
    c._wait_for_rate_limit()
    assert slept == []
