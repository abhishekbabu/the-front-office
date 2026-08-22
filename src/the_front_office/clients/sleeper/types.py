"""Types for the Sleeper API.

Sleeper is a public read-only API — no OAuth, no key, no per-user token. That
makes the football path much simpler than the Yahoo one: everything below is a
plain GET.
"""

from dataclasses import dataclass, field
from typing import Literal, TypedDict

ScoringFormat = Literal["pts_ppr", "pts_half_ppr", "pts_std"]

# Sleeper's lineup slots. FLEX and SUPER_FLEX accept several positions; BN and
# IR do not count toward a weekly score.
STARTING_SLOTS = ("QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "WRRB_FLEX", "REC_FLEX")
BENCH_SLOTS = ("BN", "IR", "TAXI")

FLEX_ELIGIBILITY: dict[str, tuple[str, ...]] = {
    "FLEX": ("RB", "WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}


class PlayerMeta(TypedDict, total=False):
    """The fields we keep from Sleeper's ~14MB player catalogue."""

    player_id: str
    name: str
    position: str
    team: str
    status: str
    injury_status: str
    depth_chart_order: int
    years_exp: int


@dataclass(frozen=True)
class NFLState:
    """Where the NFL season currently is."""

    week: int
    season: str
    season_type: str
    display_week: int

    @property
    def is_regular_season(self) -> bool:
        return self.season_type == "regular"


@dataclass(frozen=True)
class SleeperUser:
    user_id: str
    username: str
    display_name: str


@dataclass(frozen=True)
class SleeperLeague:
    league_id: str
    name: str
    season: str
    total_rosters: int
    scoring_format: ScoringFormat
    roster_positions: list[str] = field(default_factory=list)

    @property
    def starting_slots(self) -> list[str]:
        """Lineup slots that score, in the order Sleeper lists them."""
        return [s for s in self.roster_positions if s in STARTING_SLOTS]


@dataclass(frozen=True)
class SleeperRoster:
    roster_id: int
    owner_id: str
    player_ids: list[str]
    starter_ids: list[str]
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0

    @property
    def bench_ids(self) -> list[str]:
        starters = set(self.starter_ids)
        return [p for p in self.player_ids if p not in starters]

    @property
    def record(self) -> str:
        base = f"{self.wins}-{self.losses}"
        return f"{base}-{self.ties}" if self.ties else base


@dataclass(frozen=True)
class Projection:
    """A weekly projection for one player."""

    player_id: str
    name: str
    position: str
    team: str
    opponent: str
    points: float
    injury_status: str = ""

    @property
    def is_questionable(self) -> bool:
        return bool(self.injury_status) and self.injury_status.upper() not in ("", "ACTIVE")


@dataclass(frozen=True)
class TrendingPlayer:
    player_id: str
    count: int
