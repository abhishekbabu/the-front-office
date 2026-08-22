"""
Trade Engine — Orchestrates trade analysis using Gemini AI.
"""

import logging
from datetime import date
from typing import TYPE_CHECKING, Union

from yahoofantasy import League, Player  # type: ignore[import-untyped]

from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.yahoo.client import YahooFantasyClient
from the_front_office.config.constants import TRADE_PROMPT_TEMPLATE
from the_front_office.exceptions import AIResponseError, PlayerNotFoundError, TradeParseError
from the_front_office.report.mocks import MOCK_TRADE_VERDICT
from the_front_office.report.types import TradeVerdict
from the_front_office.services.context_builder import PlayerContextBuilder

if TYPE_CHECKING:
    from google.genai.chats import Chat

    from the_front_office.clients.gemini.client import GeminiClient
    from the_front_office.clients.gemini.types import MockChatSession

logger = logging.getLogger(__name__)


class TradeEvaluator:
    """
    Orchestrates trade parsing, data enrichment, and AI evaluation.
    """

    def __init__(
        self,
        league: League,
        mock_ai: bool = False,
        *,
        ai: "GeminiClient | None" = None,
        nba: NBAClient | None = None,
        yahoo: YahooFantasyClient | None = None,
    ):
        """Collaborators default to real clients; pass them in to test or reuse.

        Injection is keyword-only so the ordinary `TradeEvaluator(league)` call is unchanged.
        """
        from the_front_office.clients.gemini.client import GeminiClient

        self.ai = ai or GeminiClient(mock_mode=mock_ai)
        self.nba = nba or NBAClient()
        self.yahoo = yahoo or YahooFantasyClient(league)
        self.context_builder = PlayerContextBuilder(self.nba)

    def _resolve_players(self, player_names: list[str]) -> list[Player]:
        """Resolve player names to Yahoo Player objects.

        Raises:
            PlayerNotFoundError: any name failed to resolve. Silently dropping
                one would hand the AI a different trade than the user asked
                about, which is worse than refusing to evaluate.
        """
        resolved: list[Player] = []
        unresolved: list[str] = []
        for name in player_names:
            clean_name = name.strip()
            # 1. Try exact/standard search via Yahoo
            players = self.yahoo.search_players(clean_name)

            if not players:
                # 2. Fall back to the last name alone, which tolerates casing and
                # first-name spelling differences (e.g. "Lebron" vs "LeBron").
                parts = clean_name.split()
                if len(parts) > 1:
                    players = self.yahoo.search_players(parts[-1])

            if players:
                if len(players) > 1:
                    logger.warning(f"{len(players)} matches for {clean_name!r}; using {players[0].name.full!r}")
                resolved.append(players[0])
            else:
                unresolved.append(clean_name)

        if unresolved:
            raise PlayerNotFoundError(unresolved)
        return resolved

    def evaluate(self, trade_text: str) -> tuple[TradeVerdict, Union["Chat", "MockChatSession"]]:
        """
        Full trade evaluation flow.
        """
        # 1. Parse
        proposal = self.ai.parse_trade_string(trade_text)
        if not proposal.is_valid:
            raise TradeParseError(trade_text)

        logger.info(f"Parsed trade — giving {proposal.giving}, receiving {proposal.receiving}")

        # 2. Resolve Players
        giving_players = self._resolve_players(proposal.giving)
        receiving_players = self._resolve_players(proposal.receiving)

        # 3. Enrich Data
        # We use context builder to get the stats/schedule strings
        giving_str = self.context_builder.build_context_for_players(giving_players)
        receiving_str = self.context_builder.build_context_for_players(receiving_players)

        # 4. Team Context
        my_team = self.yahoo.get_user_team()
        matchup_context = self.yahoo.get_matchup_context(my_team)

        # Roster context is enrichment: a failure here degrades the prompt but
        # should not block the evaluation the user asked for.
        try:
            week_start, week_end = self.yahoo.get_matchup_dates(my_team)
            m_start = date.fromisoformat(week_start) if week_start else None
            m_end = date.fromisoformat(week_end) if week_end else None
            roster_str = self.context_builder.build_context_for_players(my_team.players(), m_start, m_end)
        except Exception as e:
            logger.warning(f"Failed to build roster context for trade: {e}")
            roster_str = "(Roster data unavailable)"

        # 5. Prompt
        prompt = TRADE_PROMPT_TEMPLATE.format(
            giving_str=giving_str, receiving_str=receiving_str, matchup_context=matchup_context, roster_str=roster_str
        )

        # 6. AI Analysis. Google Search stays enabled here — live injury and
        # standings news is most of the value in a trade call — and the Gemini
        # API will not accept a response schema alongside a tool. So the
        # search-grounded prose is structured in a cheap second pass.
        chat = self.ai.start_chat(enable_search=True)
        try:
            response = chat.send_message(prompt)
        except Exception as e:
            logger.error(f"Error evaluating trade: {e}")
            raise AIResponseError(f"Trade evaluation failed: {e}") from e

        if not response.text:
            raise AIResponseError("Gemini returned an empty trade evaluation.")

        verdict = self.ai.structure_text(
            response.text,
            TradeVerdict,
            instruction="Extract this NBA fantasy trade evaluation into the given structure.",
            mock=MOCK_TRADE_VERDICT,
        )
        return verdict, chat
