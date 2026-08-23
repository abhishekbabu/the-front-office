"""Provider access for the web adapter.

Sport-neutral, and deliberately free of any web framework: the API routes call
these, and so can a test with no server running. Constructing a provider is the
side-effecting part — it can open an OAuth flow — so it lives behind a function
the caller invokes only once a sport has actually been chosen.
"""

from __future__ import annotations

from typing import Any

from the_front_office.bootstrap import SportEntry, configured_sports, find
from the_front_office.domain.errors import LeagueNotFoundError


def available_sports() -> list[SportEntry]:
    """The sports this user has credentials for."""
    return configured_sports()


def build_provider(key: str) -> Any:
    """Construct the provider for a registry key, or raise if unavailable.

    Deferred until a sport is actually chosen: constructing the NBA provider
    opens a Yahoo OAuth flow, which a football-only user must never sit through.
    """
    entry = find(key)
    if entry is None:
        raise LeagueNotFoundError(f"unknown sport {key!r}")
    if not entry.is_configured():
        raise LeagueNotFoundError(f"{entry.label} is not configured — set {entry.requires} in .env")
    return entry.build()
