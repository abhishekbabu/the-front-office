"""
Scout Engine — Orchestrates data retrieval and AI analysis for scouting reports.
"""

import logging
from datetime import date
from typing import TYPE_CHECKING, Union

from yahoofantasy import League, Player  # type: ignore[import-untyped]

from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.yahoo.client import YahooFantasyClient
from the_front_office.config.constants import SCOUT_PROMPT_TEMPLATE
from the_front_office.config.settings import settings
from the_front_office.scout.types import MOCK_SCOUT_REPORT, ScoutContext, ScoutReport
from the_front_office.services import PlayerContextBuilder

if TYPE_CHECKING:
    from google.genai.chats import Chat

    from the_front_office.clients.gemini.client import GeminiClient
    from the_front_office.clients.gemini.types import MockChatSession

logger = logging.getLogger(__name__)


class Scout:
    """
    Orchestrates data retrieval and AI analysis to generate scouting reports.
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

        Injection is keyword-only so the ordinary `Scout(league)` call is unchanged.
        """
        from the_front_office.clients.gemini.client import GeminiClient

        self.ai = ai or GeminiClient(mock_mode=mock_ai)
        self.nba = nba or NBAClient()
        self.yahoo = yahoo or YahooFantasyClient(league)
        self.context_builder = PlayerContextBuilder(self.nba)

    def _build_context(self) -> ScoutContext:
        """Gather all data and build the initial AI prompt.

        Returns the prompt plus the pieces that make it up, so a follow-up
        briefing can be assembled without re-deriving or re-sending everything.
        """
        # 1. Identify User's Team — raises TeamNotFoundError if we own none.
        my_team = self.yahoo.get_user_team()

        # One matchup fetch supplies both the context block and the dates.
        matchup = self.yahoo.get_matchup(my_team)
        matchup_start: date | None = None
        matchup_end: date | None = None
        if matchup.has_dates:
            matchup_start = date.fromisoformat(matchup.week_start)
            matchup_end = date.fromisoformat(matchup.week_end)

        # 2. Transaction budget, which decides whether we can add at all.
        used_adds = my_team.roster_adds.value
        limit = settings.yahoo_max_weekly_adds
        remaining_adds = max(0, limit - used_adds)
        trans_context = (
            f"TRANSACTION CONTEXT:\n- Adds Used: {used_adds}/{limit}\n"
            f"- Remaining Adds: {remaining_adds}\n"
            "- NOTE: Prioritize aggressive streaming if adds are high, "
            "or conservative quality pickups if adds are low."
        )
        if remaining_adds > 0:
            recommendation_instructions = "Recommend **3 players** to add from the Free Agents list."
        else:
            recommendation_instructions = (
                "You have **0 adds remaining**. You CANNOT add players. Instead, identify "
                "**3 players to MONITOR** for next week who fit the team's needs."
            )

        # 3. Roster and free agents, gathered before the schedule so one bulk
        # lookup can cover every team either of them touches.
        players_list = my_team.roster().players if hasattr(my_team, "roster") else my_team.players()
        fa_players, fa_annotations = self._rank_free_agents()
        logger.debug(f"Building context for {len(players_list)} rostered and {len(fa_players)} free agents")

        remaining_games: dict[str, int] = {}
        if matchup_start and matchup_end:
            teams = [p.editorial_team_abbr for p in (*players_list, *fa_players)]
            remaining_games = self.nba.get_remaining_games_bulk(teams, matchup_start, matchup_end)

        roster_lines = self.context_builder.build_player_lines(
            players_list, matchup_start, matchup_end, remaining_games=remaining_games
        )
        fa_lines = self.context_builder.build_player_lines(
            fa_players, matchup_start, matchup_end, fa_annotations, remaining_games
        )

        # 4. Schedule summary, from the counts already in hand.
        schedule_context = ""
        if remaining_games:
            rows = "".join(
                f"- {team}: {count} games left\n"
                for team, count in sorted(remaining_games.items(), key=lambda x: x[1], reverse=True)
            )
            schedule_context = (
                f"MATCHUP PERIOD: {matchup.week_start} to {matchup.week_end}\nREMAINING GAMES BY TEAM:\n{rows}"
            )

        prompt = SCOUT_PROMPT_TEMPLATE.format(
            roster_str="".join(roster_lines.values()),
            matchup_context=matchup.context,
            fas_str="".join(fa_lines.values()),
            schedule_context=schedule_context,
            trans_context=trans_context,
            recommendation_instructions=recommendation_instructions,
        )

        return ScoutContext(
            prompt=prompt,
            matchup_context=matchup.context,
            trans_context=trans_context,
            schedule_context=schedule_context,
            roster_lines=roster_lines,
            free_agent_lines=fa_lines,
        )

    def _rank_free_agents(self) -> tuple[list[Player], dict[str, str]]:
        """Top available players per category, deduplicated, most versatile first.

        A player leading several categories appears once, annotated with all of
        them, and ahead of single-category players — the ordering the prompt
        relies on when it asks for the three best adds.
        """
        stat_leaders = self.yahoo.fetch_top_by_stat(per_stat=10)

        categories_by_key: dict[str, list[str]] = {}
        player_by_key: dict[str, Player] = {}
        for stat_name, players in stat_leaders.items():
            for p in players:
                # player_key comes off the untyped SDK object.
                key = str(p.player_key)
                if key not in categories_by_key:
                    categories_by_key[key] = []
                    player_by_key[key] = p
                categories_by_key[key].append(stat_name)

        ranked = sorted(categories_by_key.items(), key=lambda kv: len(kv[1]), reverse=True)
        players = [player_by_key[key] for key, _ in ranked]
        annotations = {key: f"[Top in: {', '.join(cats)}]" for key, cats in ranked}
        return players, annotations

    def start_analysis(self) -> tuple[ScoutReport, Union["Chat", "MockChatSession"]]:
        """Build the context, generate a validated report, and open a chat on it.

        Returns:
            The validated report and a chat session seeded with the exchange
            that produced it.

        Raises:
            TeamNotFoundError: the login owns no team in this league.
            YahooAPIError: a Yahoo request failed.
            AIUnavailableError: no Gemini credentials.
            AIResponseError: Gemini failed, or returned an invalid report.
        """
        context = self._build_context()
        report = self.ai.generate_structured(context.prompt, ScoutReport, mock=MOCK_SCOUT_REPORT)

        # Seed the chat with a briefing rather than the full prompt. The history
        # is resent on every follow-up, and the prompt's free-agent block — over
        # half its volume — is not what follow-ups ask about.
        briefing = context.briefing(report)
        logger.debug(f"Follow-up briefing is {len(briefing):,} chars vs {len(context.prompt):,} for the prompt")
        chat = self.ai.start_chat(
            initial_history=[
                {"role": "user", "parts": [briefing]},
                {"role": "model", "parts": [report.model_dump_json()]},
            ]
        )
        return report, chat

    def get_report(self) -> ScoutReport:
        """Generate a scout report (non-interactive wrapper)."""
        report, _ = self.start_analysis()
        return report
