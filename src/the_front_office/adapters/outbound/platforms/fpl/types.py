"""Types for the Fantasy Premier League API.

The official game is a public read-only JSON API — no key, no OAuth — and it is
unusual in carrying both layers at once: the same payload that lists your squad
also carries Opta-derived expected goals and assists. Nothing here needs a
second stats provider the way the NBA path does.

Money is in tenths of a million throughout, the unit the API uses: a `now_cost`
of 40 is £4.0m. Converting on the way in would lose the exact arithmetic that
transfer affordability depends on, so it is converted only for display.
"""

from dataclasses import dataclass, field
from datetime import datetime

# element_type -> the abbreviation FPL shows in its own UI.
POSITIONS: dict[int, str] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# How many of each position a legal starting eleven may hold. Also served by the
# API in `element_types`, but fixed by the rules of the game and needed to pick
# a lineup before any request has been made.
FORMATION_LIMITS: dict[str, tuple[int, int]] = {
    "GKP": (1, 1),
    "DEF": (3, 5),
    "MID": (2, 5),
    "FWD": (1, 3),
}

STARTING_SIZE = 11
SQUAD_SIZE = 15

# `status` on an element. Anything but "a" means the player may not play.
STATUS_LABELS: dict[str, str] = {
    "a": "",
    "d": "doubtful",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable",
    "n": "not in squad",
}

MAX_FREE_TRANSFERS = 5
"""Free transfers roll over, capped at five. Not exposed by the public API."""

TRANSFER_HIT = 4
"""Points deducted per transfer beyond the free allowance."""


def as_millions(tenths: int) -> str:
    """Format an API money value for display: 105 -> '£10.5m'."""
    return f"£{tenths / 10:.1f}m"


@dataclass(frozen=True)
class Gameweek:
    """One of the 38 scoring periods."""

    id: int
    name: str
    deadline: datetime
    """Aware UTC. Transfers made after this do not count for the gameweek."""

    is_current: bool = False
    is_next: bool = False
    finished: bool = False
    average_score: int = 0


@dataclass(frozen=True)
class Player:
    """One footballer, as the game scores them."""

    id: int
    name: str
    """The short name FPL displays, e.g. 'Haaland'."""

    full_name: str
    """First and second name joined, for matching a name a user typed."""

    position: str
    team: str
    """Three-letter club abbreviation, e.g. 'ARS'."""

    cost: int
    """Current price in tenths of a million."""

    expected_points: float
    """The game's own projection for the next gameweek (`ep_next`)."""

    form: float
    points_per_game: float
    total_points: int
    selected_by: float
    """Ownership percentage across all managers — how differential a pick is."""

    status: str = "a"
    news: str = ""
    chance_of_playing: int | None = None
    """Percentage, or None when the game has published no doubt."""

    minutes: int = 0
    expected_goals: float = 0.0
    expected_assists: float = 0.0
    expected_goal_involvements: float = 0.0
    expected_goals_conceded: float = 0.0
    ict_index: float = 0.0

    @property
    def is_available(self) -> bool:
        return self.status == "a"

    @property
    def availability(self) -> str:
        """A short flag for the prompt, empty when the player is fully fit."""
        label = STATUS_LABELS.get(self.status, self.status)
        if self.chance_of_playing is not None and self.chance_of_playing < 100:
            return f"{label or 'doubt'} {self.chance_of_playing}%".strip()
        return label


@dataclass(frozen=True)
class Pick:
    """One of the fifteen slots in a manager's squad for a gameweek."""

    element: int
    position: int
    """1-11 are the starting eleven, 12-15 the bench in substitution order."""

    multiplier: int
    """0 on the bench, 1 starting, 2 captained, 3 under the triple-captain chip."""

    is_captain: bool = False
    is_vice_captain: bool = False

    @property
    def is_starting(self) -> bool:
        return self.position <= STARTING_SIZE


@dataclass(frozen=True)
class Squad:
    """A manager's fifteen for one gameweek, with the money behind it."""

    gameweek: int
    picks: list[Pick]
    bank: int
    """Unspent money in tenths of a million."""

    value: int
    """Squad value in tenths of a million, excluding the bank."""

    transfers_made: int = 0
    transfers_cost: int = 0
    points_on_bench: int = 0
    active_chip: str = ""

    @property
    def budget(self) -> int:
        """What a full rebuild could spend: the squad's value plus the bank."""
        return self.value + self.bank


@dataclass(frozen=True)
class GameweekResult:
    """One row of a manager's season history, used to derive free transfers."""

    event: int
    points: int
    transfers_made: int
    transfers_cost: int


@dataclass(frozen=True)
class MiniLeague:
    """A classic league the manager is in."""

    id: int
    name: str
    rank: int
    rank_count: int
    is_private: bool
    """FPL marks invitational leagues 'x' and its own global ones 's'."""


@dataclass(frozen=True)
class Entry:
    """A manager's team."""

    entry_id: int
    name: str
    manager: str
    overall_points: int
    overall_rank: int
    current_event: int
    leagues: list[MiniLeague] = field(default_factory=list)


@dataclass(frozen=True)
class Fixture:
    """One match, with the difficulty rating the game assigns each side."""

    event: int | None
    """None for a match not yet assigned to a gameweek."""

    home: str
    away: str
    home_difficulty: int
    away_difficulty: int
    kickoff: datetime | None = None

    def opponent_of(self, team: str) -> tuple[str, int, bool] | None:
        """Who `team` faces, at what difficulty, and whether they are at home."""
        if team == self.home:
            return self.away, self.home_difficulty, True
        if team == self.away:
            return self.home, self.away_difficulty, False
        return None
