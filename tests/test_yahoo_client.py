"""Tests for YahooClient's query building and response parsing.

The client bypasses yahoofantasy's league.players() and builds Yahoo API query
strings by hand, so the query shape and the response walk are both ours to get
right. A fake context stands in for the HTTP layer.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from the_front_office.adapters.outbound.platforms.yahoo.client import YahooClient
from the_front_office.adapters.outbound.platforms.yahoo.constants import SCOUT_CATEGORIES
from the_front_office.domain.errors import (
    TeamNotFoundError,
    YahooAPIError,
    YahooLoginRequiredError,
)


@pytest.fixture(autouse=True)
def _identity_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass yahoofantasy's XML parser.

    FakeContext hands back already-parsed dicts, which is the shape the rest of
    the client works in. Parsing XML is yahoofantasy's job, not ours to retest.
    """
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(mod, "parse_response", lambda raw: raw)


def _player_payload(name: str) -> dict[str, Any]:
    return {"name": {"full": name}, "display_position": "PF", "editorial_team_abbr": "LAL"}


def _response(players: Any) -> dict[str, Any]:
    return {"fantasy_content": {"league": {"players": players}}}


class FakeContext:
    """Stands in for yahoofantasy's Context.

    Models both paths the client uses: `_load_or_fetch` for single queries, and
    the `_load` / `make_request` / `_save` split the parallel category fetch
    drives so it can keep the persistence writes on one thread.
    """

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.queries: list[str] = []
        self.raw_requests: list[str] = []
        self.saved: list[str] = []
        self.persisted: dict[str, Any] = {}
        self._access_token: str | None = "fake-token"
        self.request_threads: set[str] = set()
        self.save_threads: set[str] = set()

    def _load_or_fetch(self, cache_key: str, query: str, **kwargs: Any) -> Any:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.response

    def _load(self, persist_path: str, default: Any = None, ttl: int = 3600) -> Any:
        return self.persisted.get(persist_path, default)

    def make_request(self, query: str, **kwargs: Any) -> Any:
        import threading
        import time

        self.request_threads.add(threading.current_thread().name)
        self.raw_requests.append(query)
        if self.error:
            raise self.error
        time.sleep(0.02)  # long enough that serial execution is distinguishable
        return self.response

    def _save(self, persist_path: str, value: Any) -> None:
        import threading

        self.save_threads.add(threading.current_thread().name)
        self.saved.append(persist_path)
        self.persisted[persist_path] = value


def _client(response: Any = None, error: Exception | None = None) -> tuple[YahooClient, FakeContext]:
    ctx = FakeContext(response, error)
    league = SimpleNamespace(id="123", league_key="nba.l.123", name="My League", ctx=ctx, teams=lambda: [])
    return YahooClient(league), ctx  # type: ignore[arg-type]


# ── fetch_players ───────────────────────────────────────────────────────


# ── fetch_top_by_stat ───────────────────────────────────────────────────


def test_one_request_per_scoutable_category() -> None:
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    results = client.fetch_top_by_stat(per_stat=4)
    assert set(results) == set(SCOUT_CATEGORIES.values())
    assert len(ctx.raw_requests) == len(SCOUT_CATEGORIES)
    assert all("count=4" in q for q in ctx.raw_requests)


def test_category_requests_run_concurrently() -> None:
    """Eight independent queries were the dominant latency in a scout run."""
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    client.fetch_top_by_stat(per_stat=4)
    assert len(ctx.request_threads) > 1, "requests ran on a single thread"


def test_persistence_writes_stay_on_one_thread() -> None:
    """yahoofantasy persists to one shared pickle with a read-modify-write, so
    concurrent saves would clobber each other."""
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    client.fetch_top_by_stat(per_stat=4)
    assert len(ctx.save_threads) == 1
    assert len(ctx.saved) == len(SCOUT_CATEGORIES)


def test_cached_categories_are_not_refetched() -> None:
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    client.fetch_top_by_stat(per_stat=4)  # populates the fake cache
    before = len(ctx.raw_requests)
    client.fetch_top_by_stat(per_stat=4)  # second run should be free
    assert len(ctx.raw_requests) == before


def test_unparseable_category_response_raises() -> None:
    """A response we cannot read must not silently become an empty category."""
    client, _ = _client(_response({"player": [_player_payload("A B")]}))

    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    def _explode(raw: object) -> object:
        raise ValueError("malformed xml")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "parse_response", _explode)
        with pytest.raises(YahooAPIError, match="unreadable"):
            client.fetch_top_by_stat(per_stat=4)


def test_a_token_is_refreshed_once_before_the_pool() -> None:
    """Otherwise each worker could trigger its own refresh."""
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))
    ctx._access_token = None
    refreshes: list[int] = []

    def _refresh() -> None:
        refreshes.append(1)
        ctx._access_token = "fresh"

    ctx._get_access_token = _refresh  # type: ignore[attr-defined]
    client.fetch_top_by_stat(per_stat=4)
    assert refreshes == [1]


def test_scoreboard_is_refreshed_on_a_short_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """An hour-old scoreboard would misstate every category margin."""
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    FakeWeek.matchups_to_return = [_matchup()]
    monkeypatch.setattr(mod, "Week", FakeWeek)
    client, ctx = _client(_response(""))
    client.league.current_week = 5  # type: ignore[attr-defined]

    ttls: list[int] = []
    original = ctx._load_or_fetch

    def _record(cache_key: str, query: str, **kwargs: Any) -> Any:
        ttls.append(kwargs.get("persist_ttl", 3600))
        return original(cache_key, query, **kwargs)

    ctx._load_or_fetch = _record  # type: ignore[assignment]
    client.get_matchup(_fake_team("t1"))

    assert ttls == [mod.SCOREBOARD_TTL_SECONDS]
    assert mod.SCOREBOARD_TTL_SECONDS < 3600


def test_a_failed_scoreboard_refresh_falls_back_to_the_persisted_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    FakeWeek.matchups_to_return = [_matchup()]
    monkeypatch.setattr(mod, "Week", FakeWeek)
    client, ctx = _client(_response(""))
    client.league.current_week = 5  # type: ignore[attr-defined]

    def _boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("yahoo down")

    ctx._load_or_fetch = _boom  # type: ignore[assignment]
    info = client.get_matchup(_fake_team("t1"))
    assert info.week_start == "2026-02-09"  # still served from Week.sync


def test_unpersistable_response_is_skipped_not_fatal() -> None:
    """Persisting is best-effort; a save failure must not lose the fetch."""
    client, ctx = _client(_response({"player": [_player_payload("A B")]}))

    def _bad_save(key: str, value: Any) -> None:
        raise OSError("disk full")

    ctx._save = _bad_save  # type: ignore[assignment]
    results = client.fetch_top_by_stat(per_stat=4)
    assert all(len(v) == 1 for v in results.values())


def test_a_failing_category_raises_rather_than_silently_returning_none() -> None:
    client, _ = _client(error=RuntimeError("yahoo 500"))
    with pytest.raises(RuntimeError, match="yahoo 500"):
        client.fetch_top_by_stat(per_stat=4)


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
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: True))
    ran: list[Any] = []
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: ran.append(a))
    YahooClient.login()
    assert ran == []


def test_force_relogins_even_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: True))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "secret")
    calls: list[list[str]] = []
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    YahooClient.login(force=True)
    assert calls and calls[0][1] == "login"


def test_login_passes_credentials_and_redirect_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "the-id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "the-secret")
    calls: list[list[str]] = []
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **k: calls.append(cmd))

    YahooClient.login()
    cmd = calls[0]
    assert "the-id" in cmd
    assert "the-secret" in cmd
    assert mod.settings.yahoo_redirect_uri in cmd
    assert "8080" in cmd


def test_missing_credentials_raise_rather_than_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exiting the process is a terminal's idea of failure. Inside a server it
    takes down the request, and no inbound adapter gets to render anything."""
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", None)
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", None)

    with pytest.raises(YahooAPIError, match="must be set"):
        YahooClient.login()


def test_a_failed_login_subprocess_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess as real_subprocess

    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(YahooClient, "_token_exists", classmethod(lambda cls: False))
    monkeypatch.setattr(mod.settings, "yahoo_client_id", "id")
    monkeypatch.setattr(mod.settings, "yahoo_client_secret", "secret")

    def _fail(cmd: Any, **kwargs: Any) -> None:
        raise real_subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(mod.subprocess, "run", _fail)

    with pytest.raises(YahooLoginRequiredError):
        YahooClient.login()


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
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod

    FakeWeek.matchups_to_return = matchups
    FakeWeek.instances = []
    monkeypatch.setattr(mod, "Week", FakeWeek)
    client, _ = _client()
    client.league.current_week = current_week  # type: ignore[attr-defined]
    return client


# ── translating transport failures ──────────────────────────────────────


def _http(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(response=response)


def test_a_403_names_the_permission_that_is_actually_missing() -> None:
    """Yahoo says only "not authorized to perform this action", which reads like
    a bad token — and re-authorising a token that was never the problem is an
    afternoon. The scope on the developer app is the fix."""
    from the_front_office.adapters.outbound.platforms.yahoo.client import translate
    from the_front_office.domain.errors import YahooAuthError

    error = translate(_http(403))

    assert isinstance(error, YahooAuthError)
    assert "granted it nothing" in str(error)
    assert "yahoo-login --force" in str(error)


def test_any_other_failure_stays_a_generic_api_error() -> None:
    from the_front_office.adapters.outbound.platforms.yahoo.client import translate
    from the_front_office.domain.errors import YahooAPIError, YahooAuthError

    for error in (_http(500), _http(404), requests.exceptions.Timeout()):
        translated = translate(error)
        assert isinstance(translated, YahooAPIError)
        assert not isinstance(translated, YahooAuthError)


def test_an_error_without_a_response_is_translated_rather_than_crashing() -> None:
    """yahoofantasy raises requests' exceptions, and not all carry a response."""
    from the_front_office.adapters.outbound.platforms.yahoo.client import translate
    from the_front_office.domain.errors import YahooAPIError

    assert isinstance(translate(ValueError("unparseable")), YahooAPIError)


# ── authorisation is never obtained implicitly ──────────────────────────


def test_a_missing_token_is_reported_not_obtained(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The handshake opens a browser and blocks. A server attempting it would
    wait on a window nobody can see."""
    from the_front_office.adapters.outbound.platforms.yahoo.client import YahooClient
    from the_front_office.config.settings import settings
    from the_front_office.domain.errors import YahooLoginRequiredError

    monkeypatch.setattr(settings, "yahoo_token_file", str(tmp_path / "absent"))

    with pytest.raises(YahooLoginRequiredError, match="just yahoo-login"):
        YahooClient.ensure_authorised()


def test_an_existing_token_satisfies_the_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from the_front_office.adapters.outbound.platforms.yahoo.client import YahooClient
    from the_front_office.config.settings import settings

    token = tmp_path / ".yahoofantasy"
    token.write_text("cached", encoding="utf-8")
    monkeypatch.setattr(settings, "yahoo_token_file", str(token))

    YahooClient.ensure_authorised()  # does not raise


def test_login_without_credentials_raises_rather_than_exiting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """It used to call sys.exit, which inside a server kills the request."""
    from the_front_office.adapters.outbound.platforms.yahoo.client import YahooClient
    from the_front_office.config.settings import settings
    from the_front_office.domain.errors import YahooAPIError

    monkeypatch.setattr(settings, "yahoo_token_file", str(tmp_path / "absent"))
    monkeypatch.setattr(settings, "yahoo_client_id", None)

    with pytest.raises(YahooAPIError, match="must be set"):
        YahooClient.login()


# ── verifying a token really grants something ───────────────────────────


def test_verify_passes_when_yahoo_answers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import the_front_office.adapters.outbound.platforms.yahoo.client as mod
    from the_front_office.config.settings import settings

    token = tmp_path / ".yahoofantasy"
    token.write_text("cached", encoding="utf-8")
    monkeypatch.setattr(settings, "yahoo_token_file", str(token))
    monkeypatch.setattr(
        YahooClient, "get_context", classmethod(lambda cls: SimpleNamespace(make_request=lambda url: "<games/>"))
    )

    YahooClient.verify()  # does not raise
    assert mod  # the module under test, imported for the monkeypatch target


def test_a_token_that_authenticates_but_grants_nothing_is_caught(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The failure this exists for.

    Yahoo answers 403 rather than 401, so the token is genuinely authenticated —
    it simply carries no scope, because the app had no API permissions saved
    when it was issued. Nothing downstream can tell that apart from a
    permissions problem, so it has to be caught at the login.
    """
    from the_front_office.config.settings import settings
    from the_front_office.domain.errors import YahooAuthError

    token = tmp_path / ".yahoofantasy"
    token.write_text("cached", encoding="utf-8")
    monkeypatch.setattr(settings, "yahoo_token_file", str(token))

    def _refuse(url: str) -> str:
        raise _http(403)

    monkeypatch.setattr(YahooClient, "get_context", classmethod(lambda cls: SimpleNamespace(make_request=_refuse)))

    with pytest.raises(YahooAuthError, match="granted it nothing"):
        YahooClient.verify()


def test_an_unreachable_yahoo_is_not_reported_as_a_permission_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from the_front_office.config.settings import settings
    from the_front_office.domain.errors import YahooAPIError, YahooAuthError

    token = tmp_path / ".yahoofantasy"
    token.write_text("cached", encoding="utf-8")
    monkeypatch.setattr(settings, "yahoo_token_file", str(token))

    def _down(url: str) -> str:
        raise requests.exceptions.ConnectionError("no route")

    monkeypatch.setattr(YahooClient, "get_context", classmethod(lambda cls: SimpleNamespace(make_request=_down)))

    with pytest.raises(YahooAPIError) as caught:
        YahooClient.verify()
    assert not isinstance(caught.value, YahooAuthError)


def test_get_context_never_starts_the_browser_handshake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """It runs inside a request handler as often as from a terminal."""
    from the_front_office.config.settings import settings
    from the_front_office.domain.errors import YahooLoginRequiredError

    monkeypatch.setattr(settings, "yahoo_token_file", str(tmp_path / "absent"))
    monkeypatch.setattr(
        YahooClient, "login", classmethod(lambda cls, force=False: pytest.fail("login must not be called"))
    )

    with pytest.raises(YahooLoginRequiredError):
        YahooClient.get_context()
