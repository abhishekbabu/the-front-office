import os
import logging
from google import genai
from datetime import datetime
from typing import List, Optional
from yahoofantasy import Player, League, Team, Week  # type: ignore[import-untyped]

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

    def fetch_free_agents(self, league: League, count: int = 20) -> List[Player]:
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
            players: List[Player] = league.players(status='A')
            return players[:count]
        except Exception as e:
            logger.error(f"Error fetching players: {e}")
            # Fallback: maybe try without status or just return empty
            return []

    def _get_matchup_context(self, league: League, my_team: Team) -> str:
        """
        Fetch current week matchup, scores, and opponent roster.
        """
        try:
            current_week = getattr(league, "current_week", None)
            if not current_week:
                return ""
            
            logger.info(f"Fetching matchup context for week {current_week}")
            week = Week(league.ctx, league, current_week)
            week.sync()
            
            my_matchup = None
            for m in week.matchups:
                if m.team1.team_key == my_team.team_key or m.team2.team_key == my_team.team_key:
                    my_matchup = m
                    break
            
            if not my_matchup:
                return ""

            is_team1 = my_matchup.team1.team_key == my_team.team_key
            opponent = my_matchup.team2 if is_team1 else my_matchup.team1
            
            # Opponent Roster
            opp_roster: List[Player] = opponent.players()
            opp_roster_str = ", ".join([f"{p.name.full} ({p.display_position})" for p in opp_roster[:12]])
            
            # Matchup Score (if available)
            # Yahoo returns stats for matchups. We'll simplify for the prompt.
            context = f"\nCURRENT MATCHUP: Playing against {opponent.name}"
            context += f"\nOPPONENT KEY PLAYERS: {opp_roster_str}"
            
            return context
        except Exception as e:
            logger.warning(f"Could not fetch matchup context: {e}")
            return ""

    def get_morning_report(self, league: League) -> str:
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

        my_team_typed: Team = my_team
        roster: List[Player] = my_team_typed.players()
        roster_str = "\n".join([f"- {p.name.full} ({p.display_position})" for p in roster])

        # 2. Get Matchup Context
        matchup_context = self._get_matchup_context(league, my_team_typed)

        # 3. Get Free Agents
        fas = self.fetch_free_agents(league, count=15)
        fas_str = "\n".join([f"- {p.name.full} ({p.display_position})" for p in fas])

        if not self.client:
            return "⚠️ AI Report Unavailable: GOOGLE_API_KEY not set. (Data retrieval verified!)"

        # 4. Prompt Gemini
        prompt = f"""
You are "The Front Office" AI General Manager for an NBA Fantasy team.
Your goal is to analyze the waiver wire and suggest the best additions to the team.

CONTEXT:
- **LEAGUE TYPE**: Category League (9-cat or similar). Focus on winning individual categories, not total points.
- **STRATEGY**: Prioritize categorical balance. Identify if the team is strong or weak in specific areas (e.g., Assists, Blocks, FG%, etc.).

CONSTRAINTS:
- Identify the best player to pick up based on the roster provided.
- Consider the current matchup context to suggest players who can help win this week's categories.
- Look for statistical categories that might be missing or could be bolstered for long-term category dominance.
- Keep the report punchy, professional, and strategic.

USER'S CURRENT ROSTER:
{roster_str}

{matchup_context}

TOP AVAILABLE FREE AGENTS:
{fas_str}

INSTRUCTIONS:
1. Start with a "Morning Scout Report" header.
2. Provide a "Matchup Insight" talking briefly about the opponent's build and where we can beat them.
3. Provide a "Top Target" section with details on which specific categories they boost and why they should be added.
4. Suggest a "Drop Candidate" if applicable.
5. Keep it under 250 words.
"""

        try:
            # Using Gemini 2.5 Pro for strategy tasks
            response = self.client.models.generate_content(
                model='gemini-2.5-pro',
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
