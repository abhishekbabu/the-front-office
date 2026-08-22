"""Tests for the UI data layer."""

from datetime import datetime
from typing import Any

import pytest

from the_front_office.adapters.inbound.web import data
from the_front_office.adapters.outbound.sports.nba.yahoo import YahooNBAProvider
from the_front_office.domain.errors import LeagueNotFoundError

# ── season rollover ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 10, 20), 2026),  # opening night
        (datetime(2026, 12, 31), 2026),
        (datetime(2027, 1, 2), 2026),  # January still belongs to the prior season
        (datetime(2027, 4, 15), 2026),  # playoffs
        (datetime(2026, 9, 1), 2026),  # September boundary, inclusive
        (datetime(2026, 8, 31), 2025),  # the day before
    ],
)
def test_nba_season_rolls_over_in_september(when: datetime, expected: int) -> None:
    """Lived in the UI layer as a bare `season_year`; it is basketball's calendar
    and belongs to the basketball provider."""
    assert YahooNBAProvider.season_year(when) == expected


# ── provider construction ───────────────────────────────────────────────


def test_unknown_sport_raises() -> None:
    with pytest.raises(LeagueNotFoundError, match="unknown sport"):
        data.build_provider("cricket")


def test_an_unconfigured_sport_names_what_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A football-only user picking NBA must be told what is missing, not
    dropped into an OAuth flow."""
    with pytest.raises(LeagueNotFoundError, match="YAHOO_CLIENT_ID"):
        data.build_provider("nba")


def test_configured_sports_reflect_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from the_front_office.config.settings import settings

    assert data.available_sports() == []
    monkeypatch.setattr(settings, "sleeper_username", "someone")
    assert [e.sport for e in data.available_sports()] == ["nfl"]


def test_a_configured_sport_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    from the_front_office.config.settings import settings

    monkeypatch.setattr(settings, "sleeper_username", "someone")
    provider = data.build_provider("nfl")
    assert provider.sport == "nfl"


# ── situation parsing ───────────────────────────────────────────────────

SITUATION = """
CURRENT MATCHUP: Playing against Their Team
MATCHUP SCORE: You 5 - 4 Opponent

CATEGORY BREAKDOWN (Us vs Opponent):
- FG%: .482 vs .461
- BLK: 12 vs 17
- TO: 41 vs 38
OPPONENT KEY PLAYERS: Star Player (PG)
"""


def test_rows_are_parsed_from_the_situation_block() -> None:
    """Reuses the context already built for the AI rather than re-querying."""
    assert data.situation_rows(SITUATION) == [
        {"Category": "FG%", "You": ".482", "Opponent": ".461"},
        {"Category": "BLK", "You": "12", "Opponent": "17"},
        {"Category": "TO", "You": "41", "Opponent": "38"},
    ]


def test_non_table_lines_are_ignored() -> None:
    rows = data.situation_rows(SITUATION)
    assert all(r["Category"] not in ("CURRENT MATCHUP", "OPPONENT KEY PLAYERS") for r in rows)


def test_empty_situation_yields_no_rows() -> None:
    assert data.situation_rows("") == []


def test_a_situation_without_a_breakdown_yields_no_rows() -> None:
    """Football situations carry no category table at all."""
    assert data.situation_rows("LEAGUE: Huge Euge RR FF (14 teams)\nWEEK: 1") == []


def test_nba_client_is_constructed(monkeypatch: pytest.MonkeyPatch) -> None:
    import the_front_office.adapters.inbound.web.data as mod

    built: list[bool] = []
    monkeypatch.setattr(mod, "NBAClient", lambda: built.append(True))
    data.nba_client()
    assert built == [True]


def test_squad_rows_shape_is_shared_across_sports() -> None:
    """The team view renders whatever the provider returns, so the columns must
    agree between sports."""
    import inspect

    from the_front_office.adapters.outbound.sports.nfl.sleeper import SleeperNFLProvider

    for provider in (YahooNBAProvider, SleeperNFLProvider):
        assert "squad_rows" in dir(provider)
        sig: Any = inspect.signature(provider.squad_rows)
        assert "league_id" in sig.parameters
