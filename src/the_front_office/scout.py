"""
Scout Engine Orchestrator.
"""
import logging
from datetime import datetime
from typing import List, Optional
from yahoofantasy import League, Team  # type: ignore[import-untyped]

from the_front_office.providers.yahoo import YahooProvider
from the_front_office.config.settings import REPORT_FREE_AGENT_LIMIT
from the_front_office.config.constants import SCOUT_PROMPT_TEMPLATE
from the_front_office.providers.yahoo import YahooProvider
from the_front_office.ai.gemini import GeminiClient

logger = logging.getLogger(__name__)

class Scout:
    """
    Orchestrates data retrieval and AI analysis to generate scouting reports.
    """
    def __init__(self):
        self.ai = GeminiClient()

    def get_morning_report(self, league: League) -> str:
        """
        Generate a morning scout report for the given league.
        """
        provider = YahooProvider(league)
        
        # 1. Identify User's Team
        my_team = provider.get_user_team()
        if not my_team:
            return "⚠️ Could not identify your team in this league."
        
        # 2. Gather Context
        roster_str = "\n".join([f"- {p.name.full} ({p.display_position})" for p in my_team.players()])
        matchup_context = provider.get_matchup_context(my_team)
        
        fas = provider.fetch_free_agents(count=REPORT_FREE_AGENT_LIMIT)
        fas_str = "\n".join([f"- {p.name.full} ({p.display_position})" for p in fas])

        # 3. Analyze with AI
        prompt = SCOUT_PROMPT_TEMPLATE.format(
            roster_str=roster_str,
            matchup_context=matchup_context,
            fas_str=fas_str
        )
        
        return self.ai.generate(prompt)

def scout_league(league_name: Optional[str] = None):
    """
    Main entry point for scouting.
    """
    ctx = YahooProvider.get_context()
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

    scout = Scout()
    for league in target_leagues:
        print(f"\nScouting League: {league.name}...")
        report = scout.get_morning_report(league)
        print("\n" + "="*40)
        print(report)
        print("="*40)

if __name__ == "__main__":
    scout_league()
