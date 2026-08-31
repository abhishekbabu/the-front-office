"""
Yahoo Fantasy API constants.

STAT_CATEGORIES is the single source of truth for stat category mappings.
All stat-related logic (matchup context, scout discovery) derives from this.
"""

from thefrontoffice.adapters.outbound.platforms.yahoo.types import PlayerStat

STAT_CATEGORIES: dict[PlayerStat, str] = {
    PlayerStat.FG_PCT: "FG%",
    PlayerStat.FT_PCT: "FT%",
    PlayerStat.THREE_PTM: "3PTM",
    PlayerStat.POINTS: "PTS",
    PlayerStat.REBOUNDS: "REB",
    PlayerStat.ASSISTS: "AST",
    PlayerStat.STEALS: "ST",
    PlayerStat.BLOCKS: "BLK",
    PlayerStat.TURNOVERS: "TO",
}

# Stat categories used for scout free-agent discovery (excludes turnovers).
SCOUT_CATEGORIES: dict[PlayerStat, str] = {k: v for k, v in STAT_CATEGORIES.items() if k != PlayerStat.TURNOVERS}
