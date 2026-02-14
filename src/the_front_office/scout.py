"""
Scout Engine Orchestrator.
"""
import logging
from datetime import datetime
from typing import List, Optional
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
    def __init__(self, league: League):
        self.ai = GeminiClient()
        self.nba = NBAClient()
        self.yahoo = YahooFantasyClient(league)

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
        players = my_team.players()
        logger.info(f"Fetching stats for {len(players)} rostered players...")
        for p in players:
            stats = self.nba.get_player_stats(p.name.full)
            roster_enriched += f"- {p.name.full} ({p.display_position})"
            if stats:
                roster_enriched += f": {stats}"
            roster_enriched += "\n"

        # 3. Fetch & Enrich 25 Free Agents
        fas = self.yahoo.fetch_free_agents(count=25)
        logger.info(f"Fetching stats for top {len(fas)} free agents...")
        fas_enriched = ""
        for i, p in enumerate(fas):
            if (i + 1) % 5 == 0:
                logger.info(f"Progress: {i+1}/{len(fas)} free agents...")
            stats = self.nba.get_player_stats(p.name.full)
            fas_enriched += f"- {p.name.full} ({p.display_position})"
            if stats:
                fas_enriched += f": {stats}"
            fas_enriched += "\n"
        
        # 4. Analyze with AI
        prompt = SCOUT_PROMPT_TEMPLATE.format(
            roster_str=roster_enriched,
            matchup_context=matchup_context,
            nba_stats="", # We folded these into the specific player lists
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
