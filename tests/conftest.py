"""Shared fakes for engine tests.

The engines take their collaborators by keyword, so these stand in for Yahoo,
NBA and Gemini without any network, credentials or monkeypatching.
"""

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from the_front_office.report.mocks import MOCK_SCOUT_REPORT, MOCK_TRADE_VERDICT


def make_player(
    name: str,
    position: str = "PF",
    team: str = "LAL",
    key: str | None = None,
    status: str | None = None,
    selected_position: str | None = None,
) -> Any:
    """A duck-typed stand-in for a yahoofantasy Player."""
    player = SimpleNamespace(
        name=SimpleNamespace(full=name),
        display_position=position,
        editorial_team_abbr=team,
        player_key=key or name.lower().replace(" ", "-"),
    )
    if status:
        player.status = status
    if selected_position:
        player.selected_position = SimpleNamespace(position=selected_position)
    return player


class FakeYahoo:
    """Stands in for YahooFantasyClient."""

    def __init__(
        self,
        roster: list[Any] | None = None,
        stat_leaders: dict[str, list[Any]] | None = None,
        matchup_dates: tuple[str, str] = ("2026-02-09", "2026-02-15"),
        search_results: dict[str, list[Any]] | None = None,
        adds_used: int = 0,
    ) -> None:
        self.roster = roster if roster is not None else [make_player("Roster One")]
        self.stat_leaders = stat_leaders or {}
        self.matchup_dates = matchup_dates
        self.search_results = search_results or {}
        self.adds_used = adds_used
        self.searches: list[str] = []
        self.matchup_fetches = 0

    def get_user_team(self) -> Any:
        team = SimpleNamespace(
            name="My Team",
            roster_adds=SimpleNamespace(value=self.adds_used),
            players=lambda: self.roster,
        )
        return team

    def get_matchup(self, my_team: Any) -> Any:
        from the_front_office.clients.yahoo.types import MatchupInfo

        self.matchup_fetches += 1
        return MatchupInfo(
            context="CURRENT MATCHUP: vs Their Team\n- BLK: 12 vs 17",
            week_start=self.matchup_dates[0],
            week_end=self.matchup_dates[1],
        )

    def get_matchup_context(self, my_team: Any) -> str:
        return self.get_matchup(my_team).context

    def get_matchup_dates(self, my_team: Any) -> tuple[str, str]:
        info = self.get_matchup(my_team)
        return (info.week_start, info.week_end)

    def fetch_top_by_stat(self, per_stat: int = 10) -> dict[str, list[Any]]:
        return self.stat_leaders

    def search_players(self, query: str) -> list[Any]:
        self.searches.append(query)
        return self.search_results.get(query, [])


class FakeNBA:
    """Stands in for NBAClient."""

    def __init__(self, stats: dict[str, Any] | None = None, games: dict[str, int] | None = None) -> None:
        self.stats = stats or {}
        self.games = games or {}

    def get_player_stats(self, full_name: str) -> Any:
        return self.stats.get(full_name)

    def get_remaining_games(self, team_abbr: str, start: date, end: date) -> int:
        return self.games.get(team_abbr.upper(), 0)

    def get_remaining_games_bulk(self, teams: list[str], start: date, end: date) -> dict[str, int]:
        return {t.upper(): self.games.get(t.upper(), 0) for t in teams}


class FakeChat:
    """Stands in for a genai Chat."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_message(self, message: Any) -> Any:
        self.sent.append(str(message))
        return SimpleNamespace(text="[FAKE] follow-up answer")


class FakeAI:
    """Stands in for GeminiClient, recording what it was asked."""

    def __init__(
        self,
        report: Any = MOCK_SCOUT_REPORT,
        verdict: Any = MOCK_TRADE_VERDICT,
        proposal: Any = None,
        prose: str = "[FAKE] trade prose",
    ) -> None:
        self.report = report
        self.verdict = verdict
        self.proposal = proposal
        self.prose = prose
        self.prompts: list[str] = []
        self.structured_text: list[str] = []
        self.history: Any = None
        self.search_enabled: bool | None = None
        self.chat = FakeChat()

    def generate_structured(self, prompt: str, schema: type, mock: Any = None) -> Any:
        self.prompts.append(prompt)
        return self.report

    def structure_text(self, text: str, schema: type, instruction: str, mock: Any = None) -> Any:
        self.structured_text.append(text)
        return self.verdict

    def start_chat(self, initial_history: Any = None, enable_search: bool = False) -> FakeChat:
        self.history = initial_history
        self.search_enabled = enable_search
        return self.chat

    def parse_trade_string(self, text: str) -> Any:
        from the_front_office.trade.types import TradeProposal

        return (
            self.proposal
            if self.proposal is not None
            else TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])
        )


@pytest.fixture(autouse=True)
def _isolate_from_local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank every credential-derived setting for the duration of a test.

    `settings` is built from the developer's .env at import time. Without this a
    test asserting "unconfigured" behaviour passes in CI, which has no .env, and
    fails on a machine that does — or worse, a test quietly exercises a real
    account. Tests that need a value set it explicitly.
    """
    from the_front_office.config.settings import settings

    for field in ("sleeper_username", "sleeper_league_id", "gemini_api_key", "yahoo_client_id", "yahoo_client_secret"):
        monkeypatch.setattr(settings, field, None)


@pytest.fixture
def fake_ai() -> FakeAI:
    return FakeAI()


@pytest.fixture
def fake_nba() -> FakeNBA:
    return FakeNBA()


@pytest.fixture
def fake_yahoo() -> FakeYahoo:
    return FakeYahoo()
