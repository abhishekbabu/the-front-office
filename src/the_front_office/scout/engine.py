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
from the_front_office.scout.types import MOCK_SCOUT_REPORT, ScoutReport
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

    def _build_context(self) -> str:
        """
        Gather all data and build the initial AI prompt.
        """
        # 1. Identify User's Team — raises TeamNotFoundError if we own none.
        my_team = self.yahoo.get_user_team()

        matchup_context = self.yahoo.get_matchup_context(my_team)

        # 1b. Get matchup dates for remaining games calculation
        week_start_str, week_end_str = self.yahoo.get_matchup_dates(my_team)
        matchup_start: date | None = None
        matchup_end: date | None = None
        if week_start_str and week_end_str:
            matchup_start = date.fromisoformat(week_start_str)
            matchup_end = date.fromisoformat(week_end_str)

        # 1c. Transaction Context
        used_adds = my_team.roster_adds.value
        remaining_adds = max(0, settings.yahoo_max_weekly_adds - used_adds)
        trans_context = f"TRANSACTION CONTEXT:\n- Adds Used: {used_adds}/{settings.yahoo_max_weekly_adds}\n- Remaining Adds: {remaining_adds}\n- NOTE: Prioritize aggressive streaming if adds are high, or conservative quality pickups if adds are low."

        # Decide on recommendation task based on remaining adds
        if remaining_adds > 0:
            recommendation_instructions = "Recommend **3 players** to add from the Free Agents list."
        else:
            recommendation_instructions = "You have **0 adds remaining**. You CANNOT add players. Instead, identify **3 players to MONITOR** for next week who fit the team's needs."

        # 2. Enrich Roster with NBA Stats + Remaining Games
        players_list = my_team.roster().players if hasattr(my_team, "roster") else my_team.players()
        logger.debug(f"Fetching stats for {len(players_list)} rostered players...")
        roster_enriched = self.context_builder.build_context_for_players(players_list, matchup_start, matchup_end)

        # 3. Fetch Top Free Agents by Category (Last 7 Days)
        stat_leaders = self.yahoo.fetch_top_by_stat(per_stat=10)

        # Deduplicate: track which stats each player appears in
        seen: dict[str, list[str]] = {}  # player_key → [stat_names]
        player_map: dict[str, Player] = {}  # player_key → Player object
        for stat_name, players in stat_leaders.items():
            for p in players:
                key = p.player_key
                if key not in seen:
                    seen[key] = []
                    player_map[key] = p
                seen[key].append(stat_name)

        # Build enriched free agent string sorted by number of categories (most versatile first)
        unique_players = sorted(seen.items(), key=lambda x: len(x[1]), reverse=True)
        logger.debug(f"Fetching NBA stats for {len(unique_players)} unique free agents...")

        # Prepare list of players and annotations
        fa_players = []
        fa_annotations = {}
        for key, stat_names in unique_players:
            p = player_map[key]
            fa_players.append(p)
            fa_annotations[key] = f"[Top in: {', '.join(stat_names)}]"

        fas_enriched = self.context_builder.build_context_for_players(
            fa_players, matchup_start, matchup_end, fa_annotations
        )

        # 4. Build schedule context string
        schedule_context = ""
        if matchup_start and matchup_end:
            schedule_context = f"MATCHUP PERIOD: {week_start_str} to {week_end_str}\n"
            schedule_context += "REMAINING GAMES BY TEAM:\n"

            # Re-fetch remaining games just for the summary (a bit redundant but clean for now)
            # Optimization: context_builder could return the remaining_games dict too, but let's keep it simple.
            all_teams = set()
            for p in players_list:
                all_teams.add(p.editorial_team_abbr)
            for p in fa_players:
                all_teams.add(p.editorial_team_abbr)

            remaining_games = self.nba.get_remaining_games_bulk(list(all_teams), matchup_start, matchup_end)

            # Sort by games remaining (descending) for clarity
            for team, count in sorted(remaining_games.items(), key=lambda x: x[1], reverse=True):
                schedule_context += f"- {team}: {count} games left\n"

        # 5. Build Context
        prompt = SCOUT_PROMPT_TEMPLATE.format(
            roster_str=roster_enriched,
            matchup_context=matchup_context,
            fas_str=fas_enriched,
            schedule_context=schedule_context,
            trans_context=trans_context,
            recommendation_instructions=recommendation_instructions,
        )

        return prompt

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
        prompt = self._build_context()
        report = self.ai.generate_structured(prompt, ScoutReport, mock=MOCK_SCOUT_REPORT)

        # Seed a chat with the exchange that produced the report, so follow-ups
        # reason about it without re-sending the whole context.
        chat = self.ai.start_chat(
            initial_history=[
                {"role": "user", "parts": [prompt]},
                {"role": "model", "parts": [report.model_dump_json()]},
            ]
        )
        return report, chat

    def get_report(self) -> ScoutReport:
        """Generate a scout report (non-interactive wrapper)."""
        report, _ = self.start_analysis()
        return report
