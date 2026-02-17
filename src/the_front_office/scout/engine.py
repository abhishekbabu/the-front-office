"""
Scout Engine — Orchestrates data retrieval and AI analysis for scouting reports.
"""
import logging
from datetime import date
from typing import Dict, List, Optional, TYPE_CHECKING, Union
from yahoofantasy import League, Player  # type: ignore[import-untyped]

from the_front_office.config.constants import SCOUT_PROMPT_TEMPLATE
from the_front_office.clients.yahoo.client import YahooFantasyClient
from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.nba.types import PlayerStats, NineCatStats

if TYPE_CHECKING:
    from google.genai.chats import Chat
    from the_front_office.clients.gemini.types import MockChatSession

logger = logging.getLogger(__name__)


class Scout:
    """
    Orchestrates data retrieval and AI analysis to generate scouting reports.
    """
    def __init__(self, league: League, mock_ai: bool = False):
        from the_front_office.clients.gemini.client import GeminiClient
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

    def _get_remaining_games(
        self, team_abbr: str, matchup_start: Optional[date], matchup_end: Optional[date]
    ) -> Optional[int]:
        """Get remaining games for a player's team in the matchup period."""
        if not matchup_start or not matchup_end:
            return None
        return self.nba.get_remaining_games(team_abbr, matchup_start, matchup_end)

    def _build_context(self) -> str:
        """
        Gather all data and build the initial AI prompt.
        """
        # 1. Identify User's Team
        my_team = self.yahoo.get_user_team()
        if not my_team:
            return "⚠️ Could not identify your team in this league."

        matchup_context = self.yahoo.get_matchup_context(my_team)

        # 1b. Get matchup dates for remaining games calculation
        week_start_str, week_end_str = self.yahoo.get_matchup_dates(my_team)
        matchup_start: Optional[date] = None
        matchup_end: Optional[date] = None
        if week_start_str and week_end_str:
            matchup_start = date.fromisoformat(week_start_str)
            matchup_end = date.fromisoformat(week_end_str)

        # Pre-fetch remaining games for all teams in one pass
        remaining_games: Dict[str, int] = {}
        if matchup_start and matchup_end:
            # Collect all team abbrs from roster + free agents
            roster_teams = [p.editorial_team_abbr for p in my_team.players()]
            remaining_games = self.nba.get_remaining_games_bulk(
                roster_teams, matchup_start, matchup_end
            )
        
        # 2. Enrich Roster with NBA Stats + Remaining Games
        roster_enriched = ""
        players_list = my_team.players()
        logger.debug(f"Fetching stats for {len(players_list)} rostered players...")
        for p in players_list:
            stats_dict = self.nba.get_player_stats(p.name.full)
            games_left = remaining_games.get(p.editorial_team_abbr.upper(), None)
            games_str = f" [{games_left}G left]" if games_left is not None else ""
            roster_enriched += f"- {p.name.full} ({p.display_position}){games_str}"
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

        # Pre-fetch remaining games for free agent teams too
        if matchup_start and matchup_end:
            fa_teams = [player_map[k].editorial_team_abbr for k in seen]
            fa_remaining = self.nba.get_remaining_games_bulk(
                fa_teams, matchup_start, matchup_end
            )
            remaining_games.update(fa_remaining)

        # Build enriched free agent string sorted by number of categories (most versatile first)
        unique_players = sorted(seen.items(), key=lambda x: len(x[1]), reverse=True)
        logger.debug(f"Fetching NBA stats for {len(unique_players)} unique free agents...")
        fas_enriched = ""
        for i, (key, stat_names) in enumerate(unique_players):
            p = player_map[key]
            if (i + 1) % 5 == 0:
                logger.debug(f"Progress: {i+1}/{len(unique_players)} free agents...")
            stats_dict = self.nba.get_player_stats(p.name.full)
            categories = ", ".join(stat_names)
            games_left = remaining_games.get(p.editorial_team_abbr.upper(), None)
            games_str = f" [{games_left}G left]" if games_left is not None else ""
            fas_enriched += f"- {p.name.full} ({p.display_position}){games_str} [Top in: {categories}]"
            if stats_dict:
                fas_enriched += f": {self._format_stats(stats_dict)}"
            fas_enriched += "\n"
        
        # 4. Build schedule context string
        schedule_context = ""
        if matchup_start and matchup_end:
            schedule_context = f"MATCHUP PERIOD: {week_start_str} to {week_end_str}\n"
            schedule_context += "REMAINING GAMES BY TEAM:\n"
            # Sort by games remaining (descending) for clarity
            for team, count in sorted(remaining_games.items(), key=lambda x: x[1], reverse=True):
                schedule_context += f"- {team}: {count} games left\n"

        # 5. Build Context
        prompt = SCOUT_PROMPT_TEMPLATE.format(
            roster_str=roster_enriched,
            matchup_context=matchup_context,
            fas_str=fas_enriched,
            schedule_context=schedule_context,
        )
        
        return prompt

    def start_analysis(self) -> tuple[str, Optional[Union["Chat", "MockChatSession"]]]:
        """
        Start an interactive analysis session.
        Returns the initial report text and the chat session object.
        """
        prompt = self._build_context()
        try:
            # Start chat with empty history, then send the prompt as the first message
            chat = self.ai.start_chat()
            response = chat.send_message(prompt)
            text = response.text or "❌ No response from AI"
            return text, chat
        except Exception as e:
            logger.error(f"Error starting analysis: {e}")
            return f"❌ Error: {e}", None

    def get_report(self) -> str:
        """
        Generate a scout report (non-interactive wrapper).
        """
        report, _ = self.start_analysis()
        return report
