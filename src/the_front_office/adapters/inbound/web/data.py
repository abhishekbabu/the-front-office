"""Data access for the Streamlit UI.

Streamlit reruns the whole script on every interaction, so anything expensive or
side-effecting has to be cached or it repeats on each click. Kept separate from
app.py so it can be tested without a Streamlit runtime.

Sport-neutral: providers supply leagues and rosters. What is left here is the
one helper that reads a rendered situation block back into table rows, plus the
NBA client the Yahoo provider wants to share across reruns.
"""

from __future__ import annotations

from typing import Any

from the_front_office.adapters.outbound.platforms.nba_stats.client import NBAClient
from the_front_office.bootstrap import SportEntry, configured_sports, find
from the_front_office.domain.errors import LeagueNotFoundError


def available_sports() -> list[SportEntry]:
    """The sports this user has credentials for."""
    return configured_sports()


def build_provider(sport: str) -> Any:
    """Construct the provider for `sport`, or raise if it is not configured.

    Deferred until a sport is actually chosen: constructing the NBA provider
    opens a Yahoo OAuth flow, which a football-only user must never sit through.
    """
    entry = find(sport)
    if entry is None:
        raise LeagueNotFoundError(f"unknown sport {sport!r}")
    if not entry.is_configured():
        raise LeagueNotFoundError(f"{entry.label} is not configured — set {entry.requires} in .env")
    return entry.build()


def situation_rows(situation: str) -> list[dict[str, str]]:
    """Parse the "- LABEL: mine vs theirs" lines out of a situation block.

    Reuses the context already built for the AI rather than making a second
    round trip to the platform for numbers we have in hand.
    """
    rows = []
    for line in situation.splitlines():
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
