"""
Yahoo Fantasy API constants.

STAT_CATEGORIES is the single source of truth for stat category mappings.
All stat-related logic (matchup context, scout discovery) derives from this.
"""
from typing import Dict

from the_front_office.clients.yahoo.types import PlayerSort


# Maps stat-category PlayerSort members to their display names.
# Used by matchup context to show all 9-cat breakdowns.
STAT_CATEGORIES: Dict[PlayerSort, str] = {
    PlayerSort.FG_PCT:    "FG%",
    PlayerSort.FT_PCT:    "FT%",
    PlayerSort.THREE_PTM: "3PTM",
    PlayerSort.POINTS:    "PTS",
    PlayerSort.REBOUNDS:  "REB",
    PlayerSort.ASSISTS:   "AST",
    PlayerSort.STEALS:    "ST",
    PlayerSort.BLOCKS:    "BLK",
    PlayerSort.TURNOVERS: "TO",
}

# Stat categories used for scout free-agent discovery (excludes turnovers).
SCOUT_CATEGORIES: Dict[PlayerSort, str] = {
    k: v for k, v in STAT_CATEGORIES.items()
    if k != PlayerSort.TURNOVERS
}
