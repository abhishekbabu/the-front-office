"""The generic scouting pipeline.

Identical for every sport: ask the provider for a context, get a validated
report back from the model, and open a chat seeded with a briefing rather than
the whole prompt.
"""

import logging
from typing import TYPE_CHECKING, Union

from the_front_office.report.types import ScoutReport, SportContext
from the_front_office.sports.base import LeagueRef, SportProvider

if TYPE_CHECKING:
    from google.genai.chats import Chat

    from the_front_office.clients.gemini.client import GeminiClient
    from the_front_office.clients.gemini.types import MockChatSession

logger = logging.getLogger(__name__)


class ScoutEngine:
    """Turns any SportProvider into a scouting report."""

    def __init__(self, provider: SportProvider, mock_ai: bool = False, *, ai: "GeminiClient | None" = None):
        from the_front_office.clients.gemini.client import GeminiClient

        self.provider = provider
        self.ai = ai or GeminiClient(mock_mode=mock_ai)

    def list_leagues(self) -> list[LeagueRef]:
        return self.provider.list_leagues()

    def build_context(self, league_id: str) -> SportContext:
        return self.provider.build_context(league_id)

    def start_analysis(self, league_id: str) -> tuple[ScoutReport, Union["Chat", "MockChatSession"]]:
        """Produce a validated report and open a chat seeded with it.

        Raises:
            FrontOfficeError: the platform failed, or the model returned an
                unusable report.
        """
        from the_front_office.report.mocks import MOCK_SCOUT_REPORT

        context = self.provider.build_context(league_id)
        report = self.ai.generate_structured(context.prompt, ScoutReport, mock=MOCK_SCOUT_REPORT)

        briefing = context.briefing(report)
        logger.debug(
            f"{self.provider.sport}: briefing is {len(briefing):,} chars vs {len(context.prompt):,} for the prompt"
        )
        chat = self.ai.start_chat(
            initial_history=[
                {"role": "user", "parts": [briefing]},
                {"role": "model", "parts": [report.model_dump_json()]},
            ]
        )
        return report, chat

    def get_report(self, league_id: str) -> ScoutReport:
        """Non-interactive wrapper."""
        report, _ = self.start_analysis(league_id)
        return report
