"""
Type definitions for The Front Office.
"""
from typing import TypedDict


class NineCatStats(TypedDict):
    """Stats for the 9 standard fantasy basketball categories."""
    PTS: float
    REB: float
    AST: float
    STL: float
    BLK: float
    TOV: float
    FG3M: float
    FG_PCT: float
    FT_PCT: float


class SeasonStats(NineCatStats):
    """Season stats including games played."""
    GP: int


class PlayerStats(TypedDict, total=False):
    """Full player stats structure stored in cache.
    
    season_stats is always present; last_5/10/15 are optional 
    (only present if the player has enough games).
    """
    season_stats: SeasonStats
    last_5: NineCatStats
    last_10: NineCatStats
    last_15: NineCatStats
