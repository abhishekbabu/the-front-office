"""The seam every sport plugs into.

A sport contributes two things: how to list the user's leagues, and how to turn
one league into a rendered prompt plus the parts a follow-up briefing needs.
Everything downstream — the AI call, the chat seeding, the CLI and the UI — is
written against this protocol and knows nothing about Yahoo, Sleeper or FPL.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from the_front_office.report.types import SportContext


@dataclass(frozen=True)
class LeagueRef:
    """A league the user is in, in whatever platform the sport uses."""

    league_id: str
    name: str
    sport: str
    detail: str = ""
    """Anything worth showing beside the name — record, scoring format, team count."""


@runtime_checkable
class SportProvider(Protocol):
    """One sport on one platform."""

    sport: str
    """Short key: 'nba', 'nfl', 'fpl'."""

    label: str
    """Human name for pickers: 'NBA (Yahoo)'."""

    def list_leagues(self) -> list[LeagueRef]:
        """Every league this user plays in for the current season.

        Raises:
            FrontOfficeError: the platform is unreachable or unconfigured.
        """
        ...

    def build_context(self, league_id: str) -> SportContext:
        """Gather this league's state and render the scouting prompt.

        Raises:
            FrontOfficeError: the league or the user's team within it is missing.
        """
        ...
