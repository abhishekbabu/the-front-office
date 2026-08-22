"""The generic scouting pipeline.

Identical for every sport: ask the provider for a context, get a validated
report back from the model, and open a chat seeded with a briefing rather than
the whole prompt.
"""

import logging

from the_front_office.domain.models import ScoutReport, SportContext
from the_front_office.domain.ports import AnalysisModel, ChatSession, LeagueRef, SportProvider

logger = logging.getLogger(__name__)


class ScoutEngine:
    """Turns any SportProvider into a scouting report."""

    def __init__(self, provider: SportProvider, *, ai: AnalysisModel):
        """Both collaborators are ports, and both are supplied.

        Deliberately no default: constructing one here would mean naming a
        vendor from the application layer, which is the dependency this layer
        exists to avoid. `bootstrap.scout_engine` does the wiring.
        """
        self.provider = provider
        self.ai = ai

    def list_leagues(self) -> list[LeagueRef]:
        return self.provider.list_leagues()

    def build_context(self, league_id: str) -> SportContext:
        return self.provider.build_context(league_id)

    def start_analysis(self, league_id: str) -> tuple[ScoutReport, ChatSession]:
        """Produce a validated report and open a chat seeded with it.

        Raises:
            FrontOfficeError: the platform failed, or the model returned an
                unusable report.
        """
        from the_front_office.domain.mocks import mock_report_for

        context = self.provider.build_context(league_id)
        report = self.ai.generate_structured(context.prompt, ScoutReport, mock=mock_report_for(self.provider.sport))

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
