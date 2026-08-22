"""
Shared types for NBA data.
"""

from typing import TypedDict


class NineCatStats(TypedDict):
    PTS: float
    REB: float
    AST: float
    STL: float
    BLK: float
    TOV: float
    FG3M: float
    FG_PCT: float
    FT_PCT: float


class PlayerStats(TypedDict, total=False):
    last_5: NineCatStats
    last_10: NineCatStats
    last_15: NineCatStats


# ── Cache ──────────────────────────────────────────────────────


class GameLogRecord(TypedDict):
    GAME_DATE: str
    PTS: float
    REB: float
    AST: float
    STL: float
    BLK: float
    TOV: float
    FG3M: float
    FGA: float
    FGM: float
    FTA: float
    FTM: float


class LeagueGamelogCache(TypedDict):
    games: dict[str, list[GameLogRecord]]
    updated_at: str


class GameRecord(TypedDict):
    date: str
    """NBA game-date label (the Eastern calendar date), matching Yahoo's matchup dates."""
    tipoff_utc: str
    """Actual tip-off instant, ISO-8601 UTC. The only field that says whether a game has started."""
    status: int
    """1 = scheduled, 2 = live, 3 = final."""
    home: str
    away: str


class ScheduleCache(TypedDict):
    teams: dict[str, list[GameRecord]]
    updated_at: str


class NBACacheData(TypedDict):
    league_gamelog: LeagueGamelogCache
    schedule: ScheduleCache
