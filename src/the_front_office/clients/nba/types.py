"""
NBA stats type definitions.
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


class PlayerStats(TypedDict, total=False):
    """Recent player stats structure stored in cache.

    Each key represents a rolling window of game averages.
    Only present if the player has enough games in the log.
    """
    last_5: NineCatStats
    last_10: NineCatStats
    last_15: NineCatStats
