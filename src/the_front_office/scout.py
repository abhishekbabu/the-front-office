import os
import logging
from google import genai
from datetime import datetime
from typing import List, Any, Optional

from the_front_office.auth import get_context

logger = logging.getLogger(__name__)

class Scout:
    def __init__(self):
        # Initialize Gemini with new google.genai package
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY not found in environment. AI features will be disabled.")
            self.client = None
        else:
            # Using the new google.genai client
            self.client = genai.Client(api_key=api_key)

    def fetch_free_agents(self, league, count: int = 20) -> List[Any]:
        """
        Fetch the top available free agents.
        
        We use status='A' (All Available) as it's often more reliable than 'FA'
        in some library versions, and we can filter or just take the top ones.
        """
        logger.info(f"Fetching top {count} available players for league: {league.name}")
        
        # Note: The yahoofantasy library's League.players() method has some quirks.
        # It handles pagination internally but might fail on single-item responses
        # or specific XML structures.
        try:
            # Attempt to fetch all available players
            # The library doesn't expose 'count' directly to the user in the players() signature
            # but it uses COUNT=25 internally.
            players: List[Any] = league.players(status='A')
            return players[:count]
        except Exception as e:
            logger.error(f"Error fetching players: {e}")
            # Fallback: maybe try without status or just return empty
            return []

    def get_morning_report(self, league) -> str:
        """
        Generate a morning scout report for the given league.
        """
        # 1. Get User's Roster
        my_team = None
        for team in league.teams():
            if hasattr(team, "is_owned_by_current_login") and team.is_owned_by_current_login:
                my_team = team
                break
        
        if not my_team:
            return "⚠️ Could not identify your team in this league."

        roster = my_team.players()
        roster_str = "\n".join([f"- {p.name.full} ({p.display_position})" for p in roster])

        # 2. Get Free Agents
        fas = self.fetch_free_agents(league, count=15)
        fas_str = "\n".join([f"- {p.name.full} ({p.display_position})" for p in fas])

        if not self.client:
            return "⚠️ AI Report Unavailable: GOOGLE_API_KEY not set. (Data retrieval verified!)"

        # 3. Prompt Gemini
        prompt = f"""
You are "The Front Office" AI General Manager for an NBA Fantasy team.
Your goal is to analyze the waiver wire and suggest the best additions to the team.

CONSTRAINTS:
- Identify the best player to pick up based on the roster provided.
- Look for statistical categories that might be missing or could be bolstered.
- Keep the report punchy, professional, and strategic.

USER'S CURRENT ROSTER:
{roster_str}

TOP AVAILABLE FREE AGENTS:
{fas_str}

INSTRUCTIONS:
1. Start with a "Morning Scout Report" header.
2. Provide a "Top Target" section with details on why they should be added.
3. Suggest a "Drop Candidate" if applicable.
4. Keep it under 200 words.
"""

        try:
            # Using new google.genai API
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text or "❌ No response from AI"
        except Exception as e:
            return f"❌ Error generating AI report: {e}"

def scout_league(league_name: Optional[str] = None):
    """
    Main entry point for scouting.
    """
    ctx = get_context()
    now = datetime.now()
    season_year = now.year if now.month >= 9 else now.year - 1
    
    leagues = ctx.get_leagues("nba", season_year)
    if not leagues:
        print("No NBA leagues found.")
        return

    # Filter by name if provided
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
    # Simple test run
    scout_league()
