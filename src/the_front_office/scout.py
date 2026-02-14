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

    def get_morning_report(self) -> str:
        """
        Generate a morning scout report for the current league.
        """
        # 1. Identify User's Team
        my_team = self.yahoo.get_user_team()
        if not my_team:
            return "⚠️ Could not identify your team in this league."
        
        # 2. Gather Context
        roster_str = "\n".join([f"- {p.name.full} ({p.display_position})" for p in my_team.players()])
        matchup_context = self.yahoo.get_matchup_context(my_team)
        
        fas = self.yahoo.fetch_free_agents(count=REPORT_FREE_AGENT_LIMIT)
        fas_str = "\n".join([f"- {p.name.full} ({p.display_position})" for p in fas])

        # 3. Enrich with real-world NBA stats (Top 3 Free Agents for now)
        nba_stats = "Top Waiver Targets Trends:\n"
        for p in fas[:3]:
            stats = self.nba.get_player_stats(p.name.full)
            if stats:
                nba_stats += f"- {p.name.full}: {stats}\n"
        
        # 4. Analyze with AI
        prompt = SCOUT_PROMPT_TEMPLATE.format(
            roster_str=roster_str,
            matchup_context=matchup_context,
            nba_stats=nba_stats,
            fas_str=fas_str
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
        print(f"\nScouting League: {league.name}...")
        scout = Scout(league)
        report = scout.get_morning_report()
        print("\n" + "="*40)
        print(report)
        print("="*40)

if __name__ == "__main__":
    scout_league()
