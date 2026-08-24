"""Provider access for the web adapter.

Competition-neutral, and deliberately free of any web framework: the API routes call
these, and so can a test with no server running. Constructing a provider is the
side-effecting part — it can open an OAuth flow — so it lives behind a function
the caller invokes only once a competition has actually been chosen.
"""

from __future__ import annotations

from typing import Any

from the_front_office.bootstrap import CompetitionEntry, configured_competitions, find
from the_front_office.domain.errors import LeagueNotFoundError


def available_sports() -> list[CompetitionEntry]:
    """The competitions this user has credentials for."""
    return configured_competitions()


def build_provider(key: str) -> Any:
    """Construct the provider for a registry key, or raise if unavailable.

    Deferred until a competition is actually chosen: constructing the NBA provider
    opens a Yahoo OAuth flow, which a football-only user must never sit through.
    """
    entry = find(key)
    if entry is None:
        raise LeagueNotFoundError(f"unknown competition {key!r}")
    if not entry.is_configured():
        raise LeagueNotFoundError(f"{entry.label} is not configured — set {entry.requires} in .env")
    return entry.build()
