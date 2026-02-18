"""
Trade Engine — Orchestrates trade analysis using Gemini AI.
"""
import logging
from typing import Optional, Union, TYPE_CHECKING
from yahoofantasy import League, Player  # type: ignore[import-untyped]

from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.yahoo.client import YahooFantasyClient
from the_front_office.services.context_builder import PlayerContextBuilder

if TYPE_CHECKING:
    from google.genai.chats import Chat
    from the_front_office.clients.gemini.types import MockChatSession

logger = logging.getLogger(__name__)

from the_front_office.config.constants import TRADE_PROMPT_TEMPLATE

class TradeEvaluator:
    """
    Orchestrates trade parsing, data enrichment, and AI evaluation.
    """
    def __init__(self, league: League, mock_ai: bool = False):
        from the_front_office.clients.gemini.client import GeminiClient
        self.ai = GeminiClient(mock_mode=mock_ai)
        self.nba = NBAClient()
        self.yahoo = YahooFantasyClient(league)
        self.context_builder = PlayerContextBuilder(self.nba)

    def _resolve_players(self, player_names: list[str]) -> list[Player]:
        """
        Resolve player names to Yahoo Player objects with better robustness.
        """
        resolved = []
        for name in player_names:
            clean_name = name.strip()
            # 1. Try exact/standard search via Yahoo
            players = self.yahoo.search_players(clean_name)
            
            if not players:
                # 2. Try case-insensitive substring match against roster + free agents
                # This helps if names are slightly different (e.g. "Lebron" vs "LeBron")
                # For now, let's keep it simple and just log a better warning.
                # Heuristic: try searching for just the last name if it's a multi-word query
                parts = clean_name.split()
                if len(parts) > 1:
                    players = self.yahoo.search_players(parts[-1])
            
            if players:
                # heuristic: take the first one
                resolved.append(players[0])
            else:
                logger.warning(f"Could not find player: {name}")
        return resolved

    def evaluate(self, trade_text: str) -> tuple[str, Optional[Union["Chat", "MockChatSession"]]]:
        """
        Full trade evaluation flow.
        """
        # 1. Parse
        proposal = self.ai.parse_trade_string(trade_text)
        if not proposal.is_valid:
            return "❌ Could not parse trade. format: 'Give [players], Get [players]'", None
            
        print(f"  🔍 Parsed: Giving {proposal.giving} -> Receiving {proposal.receiving}")

        # 2. Resolve Players
        giving_players = self._resolve_players(proposal.giving)
        receiving_players = self._resolve_players(proposal.receiving)
        
        # 3. Enrich Data
        # We use context builder to get the stats/schedule strings
        giving_str = self.context_builder.build_context_for_players(
            giving_players
        )
        receiving_str = self.context_builder.build_context_for_players(
            receiving_players
        )

        # 4. Team Context
        my_team = self.yahoo.get_user_team()
        matchup_context = ""
        roster_str = "(Roster data unavailable)"

        if my_team:
            matchup_context = self.yahoo.get_matchup_context(my_team)
            
            # Fetch full roster stats for context
            try:
                week_start, week_end = self.yahoo.get_matchup_dates(my_team)
                m_start = None
                m_end = None
                from datetime import date
                if week_start and week_end:
                     m_start = date.fromisoformat(week_start)
                     m_end = date.fromisoformat(week_end)
                
                players = my_team.players()
                roster_str = self.context_builder.build_context_for_players(
                    players, m_start, m_end
                )
            except Exception as e:
                logger.warning(f"Failed to build roster context for trade: {e}")
                roster_str = "(Error fetching roster)"

        # 5. Prompt
        prompt = TRADE_PROMPT_TEMPLATE.format(
            giving_str=giving_str,
            receiving_str=receiving_str,
            matchup_context=matchup_context,
            roster_str=roster_str
        )

        # 6. AI Analysis
        try:
            # Enable Google Search for live data (injuries, standings, etc.)
            chat = self.ai.start_chat(enable_search=True)
            response = chat.send_message(prompt)
            text = response.text or "❌ No response from AI"
            return text, chat
        except Exception as e:
            logger.error(f"Error evaluating trade: {e}")
            return f"❌ Error: {e}", None
