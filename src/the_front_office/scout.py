"""
Scout Engine Orchestrator.
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from yahoofantasy import League, Team  # type: ignore[import-untyped]

from the_front_office.config.settings import REPORT_FREE_AGENT_LIMIT
from the_front_office.config.constants import SCOUT_PROMPT_TEMPLATE
from the_front_office.clients.yahoo import YahooFantasyClient
from the_front_office.clients.nba import NBAClient
from the_front_office.clients.gemini import GeminiClient

logger = logging.getLogger(__name__)

class Scout:
    """
    Orchestrates data retrieval and AI analysis to generate scouting reports.
    """
    def __init__(self, league: League, mock_ai: bool = False):
        self.ai = GeminiClient(mock_mode=mock_ai)
        self.nba = NBAClient()
        self.yahoo = YahooFantasyClient(league)

    def _format_stats(self, stats_dict: Dict[str, Any]) -> str:
        """Format structured stats dict into readable string."""
        if not stats_dict:
            return "No stats available"
        
        parts = []
        
        # Season stats (all 9-cat)
        if "season_stats" in stats_dict:
            s = stats_dict["season_stats"]
            parts.append(f"Season ({s.get('GP', 0)}GP): {s.get('PTS')}p {s.get('REB')}r {s.get('AST')}a {s.get('STL')}s {s.get('BLK')}b {s.get('TOV')}to {s.get('FG3M')}3pm FG{s.get('FG_PCT'):.1%} FT{s.get('FT_PCT'):.1%}")
        
        # Last 5/10/15
        for key, label in [("last_5", "L5"), ("last_10", "L10"), ("last_15", "L15")]:
            if key in stats_dict:
                s = stats_dict[key]
                parts.append(f"{label}: {s.get('PTS')}p {s.get('REB')}r {s.get('AST')}a")
        
        return " | ".join(parts)

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

        # 3. Fetch & Enrich 25 Free Agents
        fas = self.yahoo.fetch_free_agents(count=25)
        logger.info(f"Fetching stats for top {len(fas)} free agents...")
        fas_enriched = ""
        for i, p in enumerate(fas):
            if (i + 1) % 5 == 0:
                logger.info(f"Progress: {i+1}/{len(fas)} free agents...")
            stats_dict = self.nba.get_player_stats(p.name.full)
            fas_enriched += f"- {p.name.full} ({p.display_position})"
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

def scout_league(league_name: Optional[str] = None):
    """
    Main entry point for scouting.
    """
    ctx = YahooFantasyClient.get_context()
    now = datetime.now()
    season_year = now.year if now.month >= 9 else now.year - 1
    
    leagues = ctx.get_leagues("nba", season_year)
    if not leagues:
        print("No NBA leagues found.")
        return

    target_leagues = leagues
    if league_name:
        target_leagues = [l for l in leagues if league_name.lower() in l.name.lower()]
    
    if not target_leagues:
        print(f"No leagues matching '{league_name}' found.")
        return

    for league in target_leagues:
        scout = Scout(league)
        report = scout.get_report()
        print("\n" + "="*40)
        print(report)
        print("="*40)

if __name__ == "__main__":
    scout_league()
