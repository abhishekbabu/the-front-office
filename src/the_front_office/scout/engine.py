"""
Scout Engine — Orchestrates data retrieval and AI analysis for scouting reports.
"""
import logging
from typing import Dict, List
from yahoofantasy import League, Player  # type: ignore[import-untyped]

from the_front_office.config.constants import SCOUT_PROMPT_TEMPLATE
from the_front_office.clients.yahoo.client import YahooFantasyClient
from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.gemini.client import GeminiClient
from the_front_office.clients.nba.types import PlayerStats, NineCatStats

logger = logging.getLogger(__name__)


class Scout:
    """
    Orchestrates data retrieval and AI analysis to generate scouting reports.
    """
    def __init__(self, league: League, mock_ai: bool = False):
        self.ai = GeminiClient(mock_mode=mock_ai)
        self.nba = NBAClient()
        self.yahoo = YahooFantasyClient(league)

    def _format_stats(self, stats_dict: PlayerStats) -> str:
        """Format recent trend stats into a readable string."""
        if not stats_dict:
            return "No stats available"
        
        parts: List[str] = []
        for key, label in [("last_5", "L5"), ("last_10", "L10"), ("last_15", "L15")]:
            if key in stats_dict:
                s: NineCatStats = stats_dict[key]  # type: ignore[literal-required]
                parts.append(f"{label}: {s['PTS']}p {s['REB']}r {s['AST']}a {s['STL']}s {s['BLK']}b {s['TOV']}to {s['FG3M']}3pm FG{s['FG_PCT']:.1%} FT{s['FT_PCT']:.1%}")
        
        return " | ".join(parts) if parts else "No recent stats"

    def get_report(self) -> str:
        """
        Generate a scout report for the current league.
        """
        # 1. Identify User's Team
        my_team = self.yahoo.get_user_team()
        if not my_team:
            return "⚠️ Could not identify your team in this league."

        matchup_context = self.yahoo.get_matchup_context(my_team)
        
        # 2. Enrich Roster with NBA Stats
        roster_enriched = ""
        players_list = my_team.players()
        logger.info(f"Fetching stats for {len(players_list)} rostered players...")
        for p in players_list:
            stats_dict = self.nba.get_player_stats(p.name.full)
            roster_enriched += f"- {p.name.full} ({p.display_position})"
            if stats_dict:
                roster_enriched += f": {self._format_stats(stats_dict)}"
            roster_enriched += "\n"

        # 3. Fetch Top Free Agents by Category (Last 7 Days)
        stat_leaders = self.yahoo.fetch_top_by_stat(per_stat=5)

        # Deduplicate: track which stats each player appears in
        seen: Dict[str, List[str]] = {}  # player_key → [stat_names]
        player_map: Dict[str, Player] = {}  # player_key → Player object
        for stat_name, players in stat_leaders.items():
            for p in players:
                key = p.player_key
                if key not in seen:
                    seen[key] = []
                    player_map[key] = p
                seen[key].append(stat_name)

        # Build enriched free agent string sorted by number of categories (most versatile first)
        unique_players = sorted(seen.items(), key=lambda x: len(x[1]), reverse=True)
        logger.info(f"Fetching NBA stats for {len(unique_players)} unique free agents...")
        fas_enriched = ""
        for i, (key, stat_names) in enumerate(unique_players):
            p = player_map[key]
            if (i + 1) % 5 == 0:
                logger.info(f"Progress: {i+1}/{len(unique_players)} free agents...")
            stats_dict = self.nba.get_player_stats(p.name.full)
            categories = ", ".join(stat_names)
            fas_enriched += f"- {p.name.full} ({p.display_position}) [Top in: {categories}]"
            if stats_dict:
                fas_enriched += f": {self._format_stats(stats_dict)}"
            fas_enriched += "\n"
        
        # 4. Analyze with AI
        prompt = SCOUT_PROMPT_TEMPLATE.format(
            roster_str=roster_enriched,
            matchup_context=matchup_context,
            fas_str=fas_enriched
        )
        
        return self.ai.generate(prompt)
