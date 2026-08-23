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

    from the_front_office.adapters.outbound.platforms.sleeper.client import SleeperClient

from yahoofantasy import League, Player  # type: ignore[import-untyped]

from the_front_office.adapters.outbound.platforms.nba_stats.client import NBAStatsClient
from the_front_office.adapters.outbound.platforms.yahoo.client import YahooClient
from the_front_office.adapters.outbound.sports.nba.context import PlayerContextBuilder
from the_front_office.adapters.outbound.sports.nba.projections import ProjectionIndex
from the_front_office.adapters.outbound.sports.trades import resolve_sides
from the_front_office.config.constants import NBA_SCOUT_PROMPT, NBA_TRADE_PROMPT
from the_front_office.config.settings import settings
from the_front_office.domain.errors import FrontOfficeError, LeagueNotFoundError
from the_front_office.domain.models import SportContext, Stat, Summary, TradeProposal
from the_front_office.domain.ports import LeagueRef

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
        nba: NBAStatsClient | None = None,
        yahoo: YahooClient | None = None,
        sleeper: "SleeperClient | None" = None,
    ):
        """Collaborators default to real clients; pass them in to test or reuse."""
        self.league = league
        self._all_leagues = all_leagues or [league]
        self.nba = nba or NBAStatsClient()
        self.yahoo = yahoo or YahooClient(league)
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

    def _select_into(self, league_id: str) -> None:
        """Point this provider at `league_id`, if it is not there already."""
        league = self._select(league_id)
        if league is not self.league:
            self.league = league
            self.yahoo = YahooClient(league)

    def summary(self, league_id: str) -> Summary:
        """The header, without the free-agent pool or the model.

        Only the roster and the add budget. Yahoo hands the matchup back as
        prose it has already rendered, so there is nothing structured to lift
        out of it without parsing what the model is meant to read — and a
        category league has no lineup to set, so there is no side to show.
        """
        my_team = self.yahoo.get_user_team()
        used = my_team.roster_adds.value
        limit = settings.yahoo_max_weekly_adds
        remaining = max(0, limit - used)
        return Summary(
            headline=[
                Stat(label="Team", value=str(my_team.name)),
                Stat(label="Roster", value=str(len(list(my_team.players())))),
                Stat(label="Adds used", value=f"{used}/{limit}"),
                Stat(label="Adds left", value=str(remaining), tone="good" if remaining else "warning"),
            ]
        )

    def build_context(self, league_id: str = "") -> SportContext:
        """Gather league state and render the scouting prompt."""
        self._select_into(league_id)
        return self._build_context()

    # ── trades ──────────────────────────────────────────────────────

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> SportContext:
        """Price both sides of a trade against the current roster."""
        self._select_into(league_id)

        giving, receiving = resolve_sides(proposal, self._find_player)
        giving_str = self.context_builder.build_context_for_players(giving)
        receiving_str = self.context_builder.build_context_for_players(receiving)

        my_team = self.yahoo.get_user_team()
        matchup = self.yahoo.get_matchup(my_team)

        # Roster context is enrichment: losing it degrades the prompt but must
        # not block the evaluation the user asked for.
        try:
            start = date.fromisoformat(matchup.week_start) if matchup.has_dates else None
            end = date.fromisoformat(matchup.week_end) if matchup.has_dates else None
            roster_str = self.context_builder.build_context_for_players(my_team.players(), start, end)
        except Exception as e:
            logger.warning(f"Failed to build roster context for trade: {e}")
            roster_str = "(Roster data unavailable)"

        prompt = NBA_TRADE_PROMPT.format(
            giving_str=giving_str,
            receiving_str=receiving_str,
            matchup_context=matchup.context,
            roster_str=roster_str,
        )
        return SportContext(prompt=prompt, situation=matchup.context)

    def _find_player(self, name: str) -> Player | None:
        """The Yahoo player a name refers to, or None."""
        players = self.yahoo.search_players(name)

        if not players:
            # The surname alone tolerates casing and first-name spelling
            # differences ("Lebron" vs "LeBron").
            parts = name.split()
            if len(parts) > 1:
                players = self.yahoo.search_players(parts[-1])

        if not players:
            return None
        if len(players) > 1:
            logger.warning(f"{len(players)} matches for {name!r}; using {players[0].name.full!r}")
        return players[0]

    def roster_rows(self, league_id: str = "") -> list[dict[str, str]]:
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
            from the_front_office.adapters.outbound.platforms.sleeper.client import SleeperClient

            self._sleeper = SleeperClient()
        return self._sleeper

    def _projection_index(self, start: date | None, end: date | None) -> ProjectionIndex | None:
        """Projected category totals for the matchup period, or None.

        Returns None rather than raising when projections are unavailable —
        Sleeper publishes none before opening night, and a scout report built
        from recent form alone is the behavior this had all along.
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
        my_team = self.yahoo.get_user_team()

        # One matchup fetch supplies both the context block and the dates.
        matchup = self.yahoo.get_matchup(my_team)
        matchup_start: date | None = None
        matchup_end: date | None = None
        if matchup.has_dates:
            matchup_start = date.fromisoformat(matchup.week_start)
            matchup_end = date.fromisoformat(matchup.week_end)

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

        # Gathered before the schedule so one bulk lookup covers every team
        # either of them touches.
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

        # Schedule summary, from the counts already in hand.
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

        prompt = NBA_SCOUT_PROMPT.format(
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
            roster_lines=roster_lines,
            candidate_lines=fa_lines,
            headline=[
                Stat(label="Team", value=str(my_team.name)),
                Stat(label="Roster", value=str(len(roster_lines))),
                Stat(label="Adds used", value=f"{used_adds}/{limit}"),
                # An exhausted add budget is the constraint the whole report
                # bends around — it turns every recommendation into a MONITOR.
                Stat(
                    label="Adds left",
                    value=str(remaining_adds),
                    tone="good" if remaining_adds else "warning",
                ),
            ],
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
