"""Tests for the Sleeper API client.

Sleeper is public and read-only, so there is no auth to fake — only the HTTP
session and the disk cache.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import requests

from the_front_office.cache import JsonDiskCache
from the_front_office.clients.sleeper.client import (
    RETRY_MAX_ATTEMPTS,
    SleeperClient,
    _is_retryable,
)
from the_front_office.exceptions import SleeperAPIError


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)  # type: ignore[arg-type]

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Serves canned payloads by URL substring, counting requests."""

    def __init__(self, routes: dict[str, Any], error: Exception | None = None) -> None:
        self.routes = routes
        self.error = error
        self.requests: list[str] = []

    def get(self, url: str, timeout: int = 0) -> FakeResponse:
        self.requests.append(url)
        if self.error:
            raise self.error
        for fragment, payload in self.routes.items():
            if fragment in url:
                return FakeResponse(payload)
        return FakeResponse(None, status=404)


@pytest.fixture
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the hermetic suite fast — the backoff is real seconds otherwise."""
    import the_front_office.clients.sleeper.client as mod

    original = mod._retry
    monkeypatch.setattr(mod, "_retry", lambda: original().copy(wait=lambda _: 0))


STATE = {"week": 5, "season": "2026", "season_type": "regular", "display_week": 5}


def _client(
    routes: dict[str, Any], tmp_path: Path, error: Exception | None = None
) -> tuple[SleeperClient, FakeSession]:
    session = FakeSession(routes, error)
    return SleeperClient(cache=JsonDiskCache(tmp_path / "c.json"), session=session), session


# ── retry policy ────────────────────────────────────────────────────────


def test_network_failures_and_rate_limits_are_retryable() -> None:
    assert _is_retryable(requests.exceptions.Timeout())
    assert _is_retryable(requests.exceptions.ConnectionError())
    r = requests.Response()
    r.status_code = 429  # Sleeper's documented rate-limit code
    assert _is_retryable(requests.exceptions.HTTPError(response=r))
    r.status_code = 503
    assert _is_retryable(requests.exceptions.HTTPError(response=r))


def test_a_missing_league_is_not_retryable() -> None:
    """A 404 means the league does not exist; retrying only burns rate limit."""
    r = requests.Response()
    r.status_code = 404
    assert not _is_retryable(requests.exceptions.HTTPError(response=r))
    assert not _is_retryable(ValueError("bad json"))


def test_request_failure_becomes_a_domain_error(tmp_path: Path, no_retry_wait: None) -> None:
    client, session = _client({}, tmp_path, error=requests.exceptions.ConnectionError("down"))
    with pytest.raises(SleeperAPIError, match="Sleeper request failed"):
        client.get_nfl_state()
    assert len(session.requests) == RETRY_MAX_ATTEMPTS  # retried, then gave up


def test_a_transient_failure_then_success_is_retried(tmp_path: Path, no_retry_wait: None) -> None:
    class Flaky(FakeSession):
        def get(self, url: str, timeout: int = 0) -> FakeResponse:
            self.requests.append(url)
            if len(self.requests) == 1:
                raise requests.exceptions.Timeout()
            return FakeResponse(STATE)

    client = SleeperClient(cache=JsonDiskCache(tmp_path / "c.json"), session=Flaky({}))
    assert client.get_nfl_state().week == 5


# ── state and user ──────────────────────────────────────────────────────


def test_nfl_state_is_parsed(tmp_path: Path) -> None:
    client, _ = _client({"state/nfl": STATE}, tmp_path)
    state = client.get_nfl_state()
    assert state.week == 5
    assert state.season == "2026"
    assert state.is_regular_season


def test_preseason_is_not_the_regular_season(tmp_path: Path) -> None:
    client, _ = _client({"state/nfl": {**STATE, "season_type": "pre"}}, tmp_path)
    assert not client.get_nfl_state().is_regular_season


def test_state_is_cached_between_calls(tmp_path: Path) -> None:
    """Sleeper asks callers to stay under 1000 requests a minute."""
    client, session = _client({"state/nfl": STATE}, tmp_path)
    client.get_nfl_state()
    client.get_nfl_state()
    assert len(session.requests) == 1


def test_user_lookup_returns_the_id(tmp_path: Path) -> None:
    client, _ = _client({"user/me": {"user_id": "42", "username": "me", "display_name": "Me"}}, tmp_path)
    assert client.get_user("me").user_id == "42"


def test_unknown_user_raises(tmp_path: Path) -> None:
    client, _ = _client({"user/ghost": None}, tmp_path)
    with pytest.raises(SleeperAPIError, match="No Sleeper user"):
        client.get_user("ghost")


# ── scoring format detection ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rec_value", "expected"),
    [(1.0, "pts_ppr"), (0.75, "pts_ppr"), (0.5, "pts_half_ppr"), (0.25, "pts_half_ppr"), (0.0, "pts_std")],
)
def test_scoring_format_is_inferred_from_points_per_reception(rec_value: float, expected: str) -> None:
    """Sleeper never labels the format; getting this wrong ranks every player by
    the wrong currency."""
    assert SleeperClient.detect_scoring_format({"rec": rec_value}) == expected


def test_absent_reception_setting_is_standard() -> None:
    assert SleeperClient.detect_scoring_format({}) == "pts_std"


# ── leagues and rosters ─────────────────────────────────────────────────


LEAGUE_PAYLOAD = [
    {
        "league_id": "L1",
        "name": "Sunday Money",
        "season": "2026",
        "total_rosters": 12,
        "scoring_settings": {"rec": 1.0},
        "roster_positions": ["QB", "RB", "FLEX", "BN"],
    }
]


def test_leagues_are_parsed_with_format_and_slots(tmp_path: Path) -> None:
    client, _ = _client({"leagues/nfl": LEAGUE_PAYLOAD}, tmp_path)
    league = client.get_leagues("42", "2026")[0]
    assert league.scoring_format == "pts_ppr"
    assert league.starting_slots == ["QB", "RB", "FLEX"]  # BN excluded


def test_rosters_carry_record_and_bench(tmp_path: Path) -> None:
    payload = [
        {
            "roster_id": 1,
            "owner_id": "42",
            "players": ["a", "b", "c"],
            "starters": ["a"],
            "settings": {"wins": 3, "losses": 1, "ties": 0, "fpts": 412, "fpts_decimal": 50},
        }
    ]
    client, _ = _client({"rosters": payload}, tmp_path)
    roster = client.get_rosters("L1")[0]
    assert roster.record == "3-1"
    assert roster.bench_ids == ["b", "c"]
    assert roster.points_for == pytest.approx(412.5)


def test_a_tie_shows_in_the_record() -> None:
    from the_front_office.clients.sleeper.types import SleeperRoster

    assert SleeperRoster(1, "42", [], [], wins=2, losses=1, ties=1).record == "2-1-1"


def test_league_users_map_ids_to_names(tmp_path: Path) -> None:
    payload = [{"user_id": "42", "display_name": "Me"}, {"user_id": "43", "username": "rival"}]
    client, _ = _client({"/users": payload}, tmp_path)
    assert client.get_league_users("L1") == {"42": "Me", "43": "rival"}


# ── players and projections ─────────────────────────────────────────────


def test_catalogue_is_trimmed_to_the_fields_used(tmp_path: Path) -> None:
    """The raw response is ~14MB; caching it whole would dominate the file."""
    raw = {"1": {"full_name": "Star QB", "position": "QB", "team": "BUF", "unused": "x" * 500}}
    client, _ = _client({"players/nfl": raw}, tmp_path)
    meta = client.get_players()["1"]
    assert meta["name"] == "Star QB"
    assert "unused" not in meta


def test_catalogue_falls_back_to_first_and_last_name(tmp_path: Path) -> None:
    raw = {"1": {"first_name": "Star", "last_name": "QB", "position": "QB"}}
    client, _ = _client({"players/nfl": raw}, tmp_path)
    assert client.get_players()["1"]["name"] == "Star QB"


def test_catalogue_skips_malformed_entries(tmp_path: Path) -> None:
    client, _ = _client({"players/nfl": {"1": "not a dict"}}, tmp_path)
    assert client.get_players() == {}


def test_catalogue_is_cached(tmp_path: Path) -> None:
    """The docs ask for at most one fetch per day."""
    client, session = _client({"players/nfl": {"1": {"full_name": "A", "position": "QB"}}}, tmp_path)
    client.get_players()
    client.get_players()
    assert len([r for r in session.requests if "players/nfl" in r]) == 1


PROJECTION_PAYLOAD = [
    {
        "player_id": "1",
        "opponent": "MIA",
        "player": {"first_name": "Star", "last_name": "QB", "position": "QB", "team": "BUF"},
        "stats": {"pts_ppr": 22.4, "pts_std": 18.1},
    },
    {"player_id": "2", "player": {"first_name": "No", "last_name": "Proj"}, "stats": {}},
]


def test_projections_are_keyed_by_player_and_use_the_league_currency(tmp_path: Path) -> None:
    client, _ = _client({"projections": PROJECTION_PAYLOAD}, tmp_path)
    proj = client.get_projections("2026", 1, "pts_ppr")
    assert proj["1"].points == 22.4
    assert proj["1"].opponent == "MIA"
    assert proj["1"].name == "Star QB"


def test_a_different_scoring_format_reads_a_different_field(tmp_path: Path) -> None:
    client, _ = _client({"projections": PROJECTION_PAYLOAD}, tmp_path)
    assert client.get_projections("2026", 1, "pts_std")["1"].points == 18.1


def test_players_without_a_projection_are_omitted(tmp_path: Path) -> None:
    client, _ = _client({"projections": PROJECTION_PAYLOAD}, tmp_path)
    assert "2" not in client.get_projections("2026", 1, "pts_ppr")


def test_projection_requests_cover_every_fantasy_position(tmp_path: Path) -> None:
    client, session = _client({"projections": []}, tmp_path)
    client.get_projections("2026", 1, "pts_ppr")
    url = session.requests[0]
    for position in ("QB", "RB", "WR", "TE", "K", "DEF"):
        assert f"position[]={position}" in url


def test_injury_status_marks_a_player_questionable(tmp_path: Path) -> None:
    payload = [
        {
            "player_id": "1",
            "player": {"first_name": "Hurt", "last_name": "Guy", "position": "RB", "injury_status": "Questionable"},
            "stats": {"pts_ppr": 9.0},
        }
    ]
    client, _ = _client({"projections": payload}, tmp_path)
    assert client.get_projections("2026", 1, "pts_ppr")["1"].is_questionable


def test_a_healthy_player_is_not_questionable(tmp_path: Path) -> None:
    client, _ = _client({"projections": PROJECTION_PAYLOAD}, tmp_path)
    assert not client.get_projections("2026", 1, "pts_ppr")["1"].is_questionable


# ── trending, stats, matchups ───────────────────────────────────────────


def test_trending_players_are_parsed(tmp_path: Path) -> None:
    client, _ = _client({"trending/add": [{"player_id": "1", "count": 500}]}, tmp_path)
    trending = client.get_trending()
    assert trending[0].player_id == "1"
    assert trending[0].count == 500


def test_trending_entries_without_an_id_are_skipped(tmp_path: Path) -> None:
    client, _ = _client({"trending/add": [{"count": 5}]}, tmp_path)
    assert client.get_trending() == []


def test_stats_are_keyed_by_player(tmp_path: Path) -> None:
    client, _ = _client({"stats/nfl": {"1": {"pts_ppr": 20.0}, "bad": "x"}}, tmp_path)
    stats = client.get_stats("2026", 1)
    assert stats["1"]["pts_ppr"] == 20.0
    assert "bad" not in stats


def test_matchups_pass_through_as_raw_entries(tmp_path: Path) -> None:
    client, _ = _client({"matchups": [{"roster_id": 1, "matchup_id": 3}]}, tmp_path)
    assert client.get_matchups("L1", 3)[0]["matchup_id"] == 3


def test_an_empty_matchup_week_is_an_empty_list(tmp_path: Path) -> None:
    client, _ = _client({"matchups": None}, tmp_path)
    assert client.get_matchups("L1", 3) == []


def test_live_matchups_expire_far_sooner_than_the_catalogue() -> None:
    """Scores move during games; the player catalogue does not."""
    from the_front_office.clients.sleeper.client import MATCHUPS_TTL, PLAYERS_TTL

    assert timedelta(minutes=5) > MATCHUPS_TTL
    assert timedelta(days=1) <= PLAYERS_TTL
