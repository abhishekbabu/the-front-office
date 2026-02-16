"""
Type definitions for The Front Office.
"""
from enum import Enum
from typing import TypedDict


# ---------------------------------------------------------------------------
# Yahoo Fantasy API Enums
# ---------------------------------------------------------------------------

class PlayerStatus(str, Enum):
    """Yahoo API player status filter values."""
    ALL_AVAILABLE = "A"
    FREE_AGENT = "FA"
    WAIVERS = "W"
    TAKEN = "T"
    KEEPERS = "K"


class PlayerSort(str, Enum):
    """Yahoo API player sort field values."""
    OVERALL_RANK = "OR"
    ACTUAL_RANK = "AR"
    FANTASY_POINTS = "PTS"
    NAME = "NAME"


class SortType(str, Enum):
    """Yahoo API sort time window values."""
    SEASON = "season"
    DATE = "date"
    LAST_WEEK = "lastweek"
    LAST_MONTH = "lastmonth"


class Position(str, Enum):
    """NBA player position values."""
    POINT_GUARD = "PG"
    SHOOTING_GUARD = "SG"
    SMALL_FORWARD = "SF"
    POWER_FORWARD = "PF"
    CENTER = "C"
    GUARD = "G"
    FORWARD = "F"
    UTILITY = "Util"




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
