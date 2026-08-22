"""Tests for YahooFantasyClient's query building and response parsing.

The client bypasses yahoofantasy's league.players() and builds Yahoo API query
strings by hand, so the query shape and the response walk are both ours to get
right. A fake context stands in for the HTTP layer.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from the_front_office.clients.yahoo.client import YahooFantasyClient
from the_front_office.clients.yahoo.constants import SCOUT_CATEGORIES
from the_front_office.clients.yahoo.types import PlayerPosition, PlayerStat, PlayerStatus, Timeframe
from the_front_office.exceptions import TeamNotFoundError, YahooAPIError


def _player_payload(name: str) -> dict[str, Any]:
    return {"name": {"full": name}, "display_position": "PF", "editorial_team_abbr": "LAL"}


def _response(players: Any) -> dict[str, Any]:
    return {"fantasy_content": {"league": {"players": players}}}


class FakeContext:
    """Stands in for yahoofantasy's Context, recording the queries it is given."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.queries: list[str] = []

    def _load_or_fetch(self, cache_key: str, query: str, **kwargs: Any) -> Any:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.response


def _client(response: Any = None, error: Exception | None = None) -> tuple[YahooFantasyClient, FakeContext]:
    ctx = FakeContext(response, error)
    league = SimpleNamespace(id="123", league_key="nba.l.123", name="My League", ctx=ctx, teams=lambda: [])
    return YahooFantasyClient(league), ctx  # type: ignore[arg-type]


# ── fetch_players ───────────────────────────────────────────────────────


def test_query_encodes_every_supplied_filter() -> None:
    client, ctx = _client(_response(""))
    client.fetch_players(
        count=5,
        status=PlayerStatus.FREE_AGENT,
        sort=PlayerStat.BLOCKS,
        sort_type=Timeframe.LAST_WEEK,
        position=PlayerPosition.CENTER,
    )
    query = ctx.queries[0]
    assert query.startswith("players;")
    for fragment in ("count=5", "status=FA", "sort=18", "sort_type=lastweek", "position=C"):
        assert fragment in query


def test_optional_filters_are_omitted_when_not_given() -> None:
    client, ctx = _client(_response(""))
    client.fetch_players(count=3)
    query = ctx.queries[0]
    assert "sort=" not in query
    assert "position=" not in query
    assert "status=A" in query  # the default


def test_players_are_parsed_from_the_response() -> None:
    client, _ = _client(_response({"player": [_player_payload("A B"), _player_payload("C D")]}))
    players = client.fetch_players()
    assert [p.name.full for p in players] == ["A B", "C D"]


def test_a_single_player_is_not_treated_as_a_character_sequence() -> None:
    """Yahoo returns a bare object rather than a list when there is one result."""
    client, _ = _client(_response({"player": _player_payload("Solo Player")}))
    assert [p.name.full for p in client.fetch_players()] == ["Solo Player"]


def test_results_are_truncated_to_count() -> None:
    payload = [_player_payload(f"P{i}") for i in range(10)]
    client, _ = _client(_response({"player": payload}))
    assert len(client.fetch_players(count=3)) == 3


def test_yahoos_empty_string_container_means_no_players() -> None:
    """Yahoo returns "" rather than an empty object when nothing matches."""
    client, _ = _client(_response(""))
    assert client.fetch_players() == []


def test_missing_player_key_means_no_players() -> None:
    client, _ = _client(_response({}))
    assert client.fetch_players() == []


def test_request_failure_raises_rather_than_looking_like_an_empty_wire() -> None:
    client, _ = _client(error=RuntimeError("connection reset"))
    with pytest.raises(YahooAPIError, match="Yahoo player query failed"):
        client.fetch_players()


def test_malformed_response_raises() -> None:
    client, _ = _client({"unexpected": "shape"})
    with pytest.raises(YahooAPIError):
        client.fetch_players()


# ── fetch_top_by_stat ───────────────────────────────────────────────────


def test_one_request_per_scoutable_category() -> None:
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    results = client.fetch_top_by_stat(per_stat=4)
    assert set(results) == set(SCOUT_CATEGORIES.values())
    assert len(ctx.queries) == len(SCOUT_CATEGORIES)
    assert all("count=4" in q for q in ctx.queries)


def test_turnovers_are_not_scouted() -> None:
    """Leading the league in turnovers is not a reason to add someone."""
    assert "TO" not in SCOUT_CATEGORIES.values()


# ── get_user_team ───────────────────────────────────────────────────────


def test_the_owned_team_is_returned() -> None:
    mine = SimpleNamespace(name="Mine", is_owned_by_current_login=True)
    theirs = SimpleNamespace(name="Theirs", is_owned_by_current_login=False)
    client, _ = _client()
    client.league.teams = lambda: [theirs, mine]  # type: ignore[attr-defined]
    assert client.get_user_team() is mine


def test_owning_no_team_raises_with_the_league_name() -> None:
    client, _ = _client()
    client.league.teams = lambda: [SimpleNamespace(name="Theirs", is_owned_by_current_login=False)]  # type: ignore[attr-defined]
    with pytest.raises(TeamNotFoundError, match="My League"):
        client.get_user_team()


# ── search_players ──────────────────────────────────────────────────────


def test_search_builds_a_league_scoped_query() -> None:
    client, ctx = _client(_response({"player": [_player_payload("LeBron James")]}))
    results = client.search_players("LeBron James")
    assert "league/nba.l.123/players;search=LeBron James" in ctx.queries[0]
    assert [p.name.full for p in results] == ["LeBron James"]


def test_no_matches_is_an_empty_list_not_an_error() -> None:
    """A name that does not exist is a valid answer; a failed request is not."""
    client, _ = _client(_response(""))
    assert client.search_players("Nobody") == []


def test_search_request_failure_raises() -> None:
    client, _ = _client(error=RuntimeError("timeout"))
    with pytest.raises(YahooAPIError, match="Yahoo player search failed"):
        client.search_players("LeBron James")


def test_search_on_an_unexpected_shape_raises() -> None:
    client, _ = _client({"fantasy_content": {}})
    with pytest.raises(YahooAPIError):
        client.search_players("LeBron James")


# ── login ───────────────────────────────────────────────────────────────


def test_existing_token_skips_the_login_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    import the_front_office.clients.yahoo.client as mod

    monkeypatch.setattr(YahooFantasyClient, "_token_exists", classmethod(lambda cls: True))
    ran: list[Any] = []
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: ran.append(a))
    YahooFantasyClient.login()
    assert ran == []


def test_force_relogins_even_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import the_front_office.clients.yahoo.client as mod

    monkeypatch.setattr(YahooFantasyClient, "_token_exists", classmethod(lambda cls: True))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "secret")
    calls: list[list[str]] = []
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    YahooFantasyClient.login(force=True)
    assert calls and calls[0][1] == "login"


def test_login_passes_credentials_and_redirect_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    import the_front_office.clients.yahoo.client as mod

    monkeypatch.setattr(YahooFantasyClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "the-id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "the-secret")
    calls: list[list[str]] = []
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **k: calls.append(cmd))

    YahooFantasyClient.login()
    cmd = calls[0]
    assert "the-id" in cmd
    assert "the-secret" in cmd
    assert mod.settings.yahoo_redirect_uri in cmd
    assert "8080" in cmd


def test_missing_credentials_exit_with_a_message(monkeypatch: pytest.MonkeyPatch) -> None:
    import the_front_office.clients.yahoo.client as mod

    monkeypatch.setattr(YahooFantasyClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", None)
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", None)
    with pytest.raises(SystemExit):
        YahooFantasyClient.login()


def test_failed_login_subprocess_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess as real_subprocess

    import the_front_office.clients.yahoo.client as mod

    monkeypatch.setattr(YahooFantasyClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "secret")

    def _fail(cmd: Any, **kwargs: Any) -> None:
        raise real_subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(mod.subprocess, "run", _fail)
    with pytest.raises(SystemExit):
        YahooFantasyClient.login()


# ── matchup context ─────────────────────────────────────────────────────


class FakeWeek:
    """Stands in for yahoofantasy's Week."""

    instances: list["FakeWeek"] = []

    def __init__(self, ctx: Any, league: Any, week_num: Any) -> None:
        self.matchups = FakeWeek.matchups_to_return
        FakeWeek.instances.append(self)

    matchups_to_return: list[Any] = []

    def sync(self) -> None:
        pass


def _fake_team(team_key: str) -> Any:
    """A duck-typed Team; the client only reads .team_key off it."""
    return SimpleNamespace(team_key=team_key)


def _stat(stat_id: str, value: str) -> Any:
    return SimpleNamespace(stat_id=stat_id, value=value)


def _team_data(points: str, stats: list[Any]) -> Any:
    return SimpleNamespace(
        team_stats=SimpleNamespace(stats=SimpleNamespace(stat=stats)),
        team_points=SimpleNamespace(total=points),
    )


def _matchup(my_key: str = "t1") -> Any:
    mine = SimpleNamespace(team_key=my_key, name="Mine", players=lambda: [])
    theirs = SimpleNamespace(
        team_key="t2",
        name="Theirs",
        players=lambda: [SimpleNamespace(name=SimpleNamespace(full="Star Player"), display_position="PG")],
    )
    return SimpleNamespace(
        team1=mine,
        team2=theirs,
        week_start="2026-02-09",
        week_end="2026-02-15",
        teams=SimpleNamespace(team=[_team_data("50", [_stat("18", "12")]), _team_data("60", [_stat("18", "17")])]),
    )


def _matchup_client(monkeypatch: pytest.MonkeyPatch, matchups: list[Any], current_week: Any = 5) -> Any:
    import the_front_office.clients.yahoo.client as mod

    FakeWeek.matchups_to_return = matchups
    FakeWeek.instances = []
    monkeypatch.setattr(mod, "Week", FakeWeek)
    client, _ = _client()
    client.league.current_week = current_week  # type: ignore[attr-defined]
    return client


def test_matchup_dates_come_from_the_users_matchup(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _matchup_client(monkeypatch, [_matchup()])
    assert client.get_matchup_dates(_fake_team("t1")) == ("2026-02-09", "2026-02-15")


def test_no_current_week_yields_no_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _matchup_client(monkeypatch, [_matchup()], current_week=None)
    assert client.get_matchup_dates(_fake_team("t1")) == ("", "")


def test_a_team_not_in_any_matchup_yields_no_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _matchup_client(monkeypatch, [_matchup()])
    assert client.get_matchup_dates(_fake_team("nope")) == ("", "")


def test_matchup_context_reports_opponent_score_and_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _matchup_client(monkeypatch, [_matchup()])
    context = client.get_matchup_context(_fake_team("t1"))
    assert "Theirs" in context
    assert "You 50 - 60 Opponent" in context
    assert "BLK: 12 vs 17" in context
    assert "Star Player" in context


def test_matchup_context_is_empty_when_there_is_no_matchup(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _matchup_client(monkeypatch, [])
    assert client.get_matchup_context(_fake_team("t1")) == ""


def test_matchup_failures_degrade_to_empty_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Matchup context is enrichment — losing it must not lose the report."""
    import the_front_office.clients.yahoo.client as mod

    class Exploding(FakeWeek):
        def sync(self) -> None:
            raise RuntimeError("yahoo hiccup")

    monkeypatch.setattr(mod, "Week", Exploding)
    client, _ = _client()
    client.league.current_week = 5  # type: ignore[attr-defined]
    assert client.get_matchup_context(_fake_team("t1")) == ""
    assert client.get_matchup_dates(_fake_team("t1")) == ("", "")
