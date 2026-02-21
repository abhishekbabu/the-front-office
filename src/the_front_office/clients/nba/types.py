"""
Shared types for NBA data.
"""
from typing import TypedDict, Optional

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


# --- Cache Specific Types ---

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
    status: int
    home: str
    away: str

class ScheduleCache(TypedDict):
    teams: dict[str, list[GameRecord]]
    updated_at: str

class NBACacheData(TypedDict):
    league_gamelog: LeagueGamelogCache
    schedule: ScheduleCache
