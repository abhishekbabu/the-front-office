"""Cached data access for the Streamlit UI.

Streamlit reruns the whole script on every interaction, so anything expensive or
side-effecting has to be cached or it repeats on each click. Kept separate from
app.py so it can be tested without a Streamlit runtime: every function here is a
thin wrapper whose uncached body is importable and exercised directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.yahoo.client import YahooFantasyClient


def season_year(now: datetime | None = None) -> int:
    """The NBA season a date belongs to. Seasons start in October."""
    moment = now or datetime.now()
    return moment.year if moment.month >= 9 else moment.year - 1


def load_leagues() -> list[Any]:
    """Authenticate once and list this season's NBA leagues."""
    YahooFantasyClient.login()
    ctx = YahooFantasyClient.get_context()
    return list(ctx.get_leagues("nba", season_year()))


def roster_rows(team: Any) -> list[dict[str, str]]:
    """Flatten a Yahoo roster into table rows."""
    rows = []
    for player in team.players():
        slot = getattr(getattr(player, "selected_position", None), "position", "")
        status = getattr(player, "status", "") or ""
        rows.append(
            {
                "Player": player.name.full,
                "Pos": player.display_position,
                "Team": player.editorial_team_abbr,
                "Slot": slot,
                "Status": status,
            }
        )
    return rows


def matchup_rows(context: str) -> list[dict[str, str]]:
    """Parse the category breakdown out of a matchup context string.

    The context is built for the AI prompt; this pulls the same numbers back out
    for display rather than making a second Yahoo round trip.
    """
    rows = []
    for line in context.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or " vs " not in stripped:
            continue
        label, _, values = stripped[2:].partition(":")
        mine, _, theirs = values.strip().partition(" vs ")
        rows.append({"Category": label.strip(), "You": mine.strip(), "Opponent": theirs.strip()})
    return rows


def nba_client() -> NBAClient:
    """One NBAClient per session — it reads the cache file on construction."""
    return NBAClient()
