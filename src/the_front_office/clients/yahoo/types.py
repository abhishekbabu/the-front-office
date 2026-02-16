"""
Yahoo Fantasy API type definitions.
"""
from enum import Enum


class PlayerStatus(str, Enum):
    """Yahoo API player status filter values."""
    ALL_AVAILABLE = "A"
    FREE_AGENT = "FA"
    WAIVERS = "W"
    TAKEN = "T"
    KEEPERS = "K"


class PlayerStat(str, Enum):
    """Yahoo API player stat / sort field values."""
    OVERALL_RANK = "OR"
    ACTUAL_RANK = "AR"
    FANTASY_POINTS = "PTS"
    NAME = "NAME"
    # Stat category IDs (sort by individual stat)
    FG_PCT = "5"
    FT_PCT = "8"
    THREE_PTM = "10"
    POINTS = "12"
    REBOUNDS = "15"
    ASSISTS = "16"
    STEALS = "17"
    BLOCKS = "18"
    TURNOVERS = "19"


class Timeframe(str, Enum):
    """Yahoo API time window values for sorting."""
    SEASON = "season"
    DATE = "date"
    LAST_WEEK = "lastweek"
    LAST_MONTH = "lastmonth"


class PlayerPosition(str, Enum):
    """NBA player position values."""
    POINT_GUARD = "PG"
    SHOOTING_GUARD = "SG"
    SMALL_FORWARD = "SF"
    POWER_FORWARD = "PF"
    CENTER = "C"
    GUARD = "G"
    FORWARD = "F"
    UTILITY = "Util"
