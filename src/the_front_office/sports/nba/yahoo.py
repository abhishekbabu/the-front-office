"""NBA on Yahoo.

Category-league basketball: the forward-looking number is games remaining in the
matchup period crossed with recent per-category form, and the budget constraint
is Yahoo's weekly add limit.
"""

import logging
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from the_front_office.clients.sleeper.client import SleeperClient

from yahoofantasy import League, Player  # type: ignore[import-untyped]

from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.yahoo.client import YahooFantasyClient
from the_front_office.config.constants import SCOUT_PROMPT_TEMPLATE
from the_front_office.config.settings import settings
from the_front_office.exceptions import FrontOfficeError, LeagueNotFoundError
from the_front_office.report.types import SportContext
from the_front_office.sports.base import LeagueRef
from the_front_office.sports.nba.context import PlayerContextBuilder
from the_front_office.sports.nba.projections import ProjectionIndex

logger = logging.getLogger(__name__)


class YahooNBAProvider:
    """SportProvider for Yahoo category-league basketball."""

    sport = "nba"
    label = "NBA (Yahoo)"

    @staticmethod
    def season_year(now: "datetime | None" = None) -> int:
        """The NBA season a date belongs to. Seasons start in October."""
        from datetime import datetime as _dt

        moment = now or _dt.now()
        return moment.year if moment.month >= 9 else moment.year - 1

    def __init__(
        self,
        league: League,
        *,
        all_leagues: list[League] | None = None,
        nba: NBAClient | None = None,
        yahoo: YahooFantasyClient | None = None,
        sleeper: "SleeperClient | None" = None,
    ):
        """Collaborators default to real clients; pass them in to test or reuse."""
        self.league = league
        self._all_leagues = all_leagues or [league]
        self.nba = nba or NBAClient()
        self.yahoo = yahoo or YahooFantasyClient(league)
        self.context_builder = PlayerContextBuilder(self.nba)
        # Sleeper is the projection source. It is separate from the Yahoo league
        # and the nba_api box scores: Yahoo says who is on the roster, nba_api
        # says what they have done, Sleeper says what they are expected to do.
        self._sleeper = sleeper

    def list_leagues(self) -> list[LeagueRef]:
        """Every Yahoo NBA league this login is in."""
        return [
            LeagueRef(
                league_id=str(lg.id),
                name=str(lg.name),
                sport=self.sport,
                detail=str(getattr(lg, "league_type", "")),
            )
            for lg in self._all_leagues
        ]

    def _select(self, league_id: str) -> League:
        """The league object for `league_id`, defaulting to the current one."""
        if not league_id:
            return self.league
        for lg in self._all_leagues:
            if str(lg.id) == str(league_id):
                return lg
        raise LeagueNotFoundError(f"Yahoo league {league_id} is not one of yours")

    def build_context(self, league_id: str = "") -> SportContext:
        """Gather league state and render the scouting prompt."""
        league = self._select(league_id)
        if league is not self.league:
            self.league = league
            self.yahoo = YahooFantasyClient(league)
        return self._build_context()

    def squad_rows(self, league_id: str = "") -> list[dict[str, str]]:
        """The user's roster as table rows, for a team view."""
        team = self.yahoo.get_user_team()
        rows = []
        for player in team.players():
            rows.append(
                {
                    "Player": str(player.name.full),
                    "Pos": str(player.display_position),
                    "Team": str(player.editorial_team_abbr),
                    "Slot": str(getattr(getattr(player, "selected_position", None), "position", "")),
                    "Status": str(getattr(player, "status", "") or ""),
                }
            )
        return rows

    @property
    def sleeper(self) -> "SleeperClient":
        """Lazily constructed — no credentials needed, but no reason to build it
        until a report is actually run."""
        if self._sleeper is None:
            from the_front_office.clients.sleeper.client import SleeperClient

            self._sleeper = SleeperClient()
        return self._sleeper

    def _projection_index(self, start: date | None, end: date | None) -> ProjectionIndex | None:
        """Projected category totals for the matchup period, or None.

        Returns None rather than raising when projections are unavailable —
        Sleeper publishes none before opening night, and a scout report built
        from recent form alone is the behaviour this had all along.
        """
        if start is None or end is None:
            return None
        try:
            state = self.sleeper.get_state("nba")
            rows = self.sleeper.get_nba_projections(state.season, state.week)
            if not rows and state.week:
                # A matchup can straddle two Sleeper weeks near a boundary.
                rows = self.sleeper.get_nba_projections(state.season, state.week + 1)
            index = ProjectionIndex(rows, start, end)
        except FrontOfficeError as e:
            logger.warning(f"No NBA projections available, using recent form only: {e}")
            return None

        if index.is_empty:
            logger.info("Sleeper has no NBA projections for this period (out of season?)")
            return None
        logger.debug(f"Matched projections for {len(index)} players")
        return index

    def _build_context(self) -> SportContext:
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

        projections = self._projection_index(matchup_start, matchup_end)
        roster_lines = self.context_builder.build_player_lines(
            players_list,
            matchup_start,
            matchup_end,
            remaining_games=remaining_games,
            projections=projections,
        )
        fa_lines = self.context_builder.build_player_lines(
            fa_players,
            matchup_start,
            matchup_end,
            fa_annotations,
            remaining_games,
            projections=projections,
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

        projection_note = (
            "PROJECTIONS: lines marked PROJ carry projected totals for this matchup period — "
            "games, then the nine categories. Prefer them to recent form when the two disagree, "
            "since they already account for the schedule and expected minutes.\n"
            "- The bracketed [NG left] is how many games the player's TEAM has left. The PROJ "
            "game count is how many that PLAYER is expected to play. A player whose PROJ count "
            "is lower than his team's is expected to miss games — treat the gap as a warning, "
            "not a contradiction.\n"
            if projections is not None
            else "PROJECTIONS: unavailable for this period. Reason from recent form and games "
            "remaining, and say so rather than implying a forecast.\n"
        )
        schedule_context = projection_note + schedule_context

        prompt = SCOUT_PROMPT_TEMPLATE.format(
            roster_str="".join(roster_lines.values()),
            matchup_context=matchup.context,
            fas_str="".join(fa_lines.values()),
            schedule_context=schedule_context,
            trans_context=trans_context,
            recommendation_instructions=recommendation_instructions,
        )

        return SportContext(
            prompt=prompt,
            situation=matchup.context,
            constraints=trans_context,
            extra=schedule_context,
            squad_lines=roster_lines,
            candidate_lines=fa_lines,
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
