"""NFL on Sleeper.

Points-scoring football: the forward-looking number is Sleeper's own weekly
projection in the league's scoring currency, and the binding constraints are the
starting lineup slots rather than a transaction budget.

Unlike the Yahoo path there is no OAuth — Sleeper's API is public, so a username
is the only configuration.
"""

import logging
from dataclasses import dataclass

from the_front_office.adapters.outbound.platforms.sleeper.client import NFL, SleeperClient
from the_front_office.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from the_front_office.adapters.outbound.sports.names import NameIndex
from the_front_office.adapters.outbound.sports.nfl.lineup import (
    LineupChange,
    LineupSlot,
    current_lineup,
    lineup_changes,
    lineup_points,
    optimal_lineup,
)
from the_front_office.adapters.outbound.sports.trades import resolve_sides
from the_front_office.config.constants import NFL_SCOUT_PROMPT, NFL_TRADE_PROMPT
from the_front_office.config.settings import settings
from the_front_office.domain.errors import LeagueNotFoundError, PlayerNotFoundError, SleeperAPIError
from the_front_office.domain.models import (
    PlayerCard,
    PlayerDetail,
    Side,
    SportContext,
    Spot,
    Stat,
    Summary,
    Swap,
    Tone,
    TradeProposal,
)
from the_front_office.domain.ports import LeagueRef

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Week:
    """One week's state, gathered once and read by both callers."""

    league: SleeperLeague
    roster: SleeperRoster
    week: int
    season: str
    projections: dict[str, WeeklyProjection]
    players: dict[str, PlayerMeta]
    projected: list[WeeklyProjection]
    lineup: list[LineupSlot]
    best: list[LineupSlot]
    changes: list[LineupChange]
    current_points: float
    best_points: float
    on_bench: float


SCORING_LABELS = {
    "pts_ppr": "Full PPR (1 point per reception)",
    "pts_half_ppr": "Half PPR (0.5 per reception)",
    "pts_std": "Standard (no point per reception)",
}

AVAILABLE_PLAYER_LIMIT = 25
TRENDING_LIMIT = 10


class SleeperNFLProvider:
    """SportProvider for Sleeper points-league football."""

    sport = "nfl"
    label = "NFL (Sleeper)"

    def __init__(self, username: str | None = None, *, client: SleeperClient | None = None):
        self.username = username or settings.sleeper_username
        self.client = client or SleeperClient()
        self._user_id: str | None = None

    # ── leagues ─────────────────────────────────────────────────────

    def _resolve_user_id(self) -> str:
        if self._user_id:
            return self._user_id
        if not self.username:
            raise LeagueNotFoundError("SLEEPER_USERNAME is not set in .env")
        self._user_id = self.client.get_user(self.username).user_id
        return self._user_id

    def list_leagues(self) -> list[LeagueRef]:
        state = self.client.get_nfl_state()
        leagues = self.client.get_leagues(self._resolve_user_id(), state.season)
        return [
            LeagueRef(
                league_id=lg.league_id,
                name=lg.name,
                sport=self.sport,
                detail=f"{lg.total_rosters}-team · {SCORING_LABELS.get(lg.scoring_format, lg.scoring_format)}",
            )
            for lg in leagues
        ]

    def _league(self, league_id: str) -> SleeperLeague:
        state = self.client.get_nfl_state()
        for lg in self.client.get_leagues(self._resolve_user_id(), state.season):
            if lg.league_id == league_id:
                return lg
        raise LeagueNotFoundError(f"league {league_id} is not one of yours this season")

    def _my_roster(self, league_id: str) -> SleeperRoster:
        user_id = self._resolve_user_id()
        for roster in self.client.get_rosters(league_id):
            if roster.owner_id == user_id:
                return roster
        raise LeagueNotFoundError(f"you do not own a roster in league {league_id}")

    def roster(self, league_id: str) -> list[PlayerCard]:
        """The full roster, with the depth and experience a week view leaves out."""
        state = self._week(league_id)
        starters = set(state.roster.starter_ids)
        scheduled = any(p.opponent for p in state.projected)

        cards = []
        for player_id in state.roster.player_ids:
            meta = state.players.get(player_id)
            if not meta:
                continue
            projection = state.projections.get(player_id)
            injury = str(meta.get("injury_status") or "")
            depth = int(meta.get("depth_chart_order") or 0)
            cards.append(
                PlayerCard(
                    player_id=player_id,
                    tone="warning" if injury else "neutral",
                    columns={
                        "Player": str(meta.get("name") or player_id),
                        "Pos": str(meta.get("position") or ""),
                        "Team": str(meta.get("team") or "FA"),
                        "Slot": "START" if player_id in starters else "BN",
                        "Proj": f"{projection.points:.1f}" if projection else "0.0",
                        "Opponent": self._opponent_label(projection, scheduled),
                        "Depth": str(depth) if depth else "—",
                        "Exp": f"{int(meta.get('years_exp') or 0)}y",
                        "Status": injury,
                    },
                )
            )
        return cards

    @staticmethod
    def _opponent_label(projection: WeeklyProjection | None, scheduled: bool) -> str:
        if projection and projection.opponent:
            return f"vs {projection.opponent}"
        return "no game" if scheduled else "—"

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player, as this week and the depth chart see them."""
        state = self._week(league_id)
        meta = state.players.get(player_id)
        if meta is None:
            raise PlayerNotFoundError([player_id])

        projection = state.projections.get(player_id)
        scheduled = any(p.opponent for p in state.projected)
        depth = int(meta.get("depth_chart_order") or 0)
        injury = str(meta.get("injury_status") or "")
        return PlayerDetail(
            player_id=player_id,
            name=str(meta.get("name") or player_id),
            position=str(meta.get("position") or ""),
            team=str(meta.get("team") or "FA"),
            headline=f"{projection.points:.1f} proj pts" if projection else "no projection",
            note=injury,
            tone="warning" if injury else "neutral",
            stats=[
                Stat(label=f"Week {state.week}", value=self._opponent_label(projection, scheduled)),
                Stat(label="Depth chart", value=f"{depth}" if depth else "unlisted"),
                Stat(label="Experience", value=f"{int(meta.get('years_exp') or 0)} seasons"),
                Stat(label="Status", value=str(meta.get("status") or "active")),
            ],
        )

    # ── trades ──────────────────────────────────────────────────────

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> SportContext:
        """Price both sides of a trade against the current roster."""
        league = self._league(league_id)
        roster = self._my_roster(league_id)
        week, season = self._current_week(), self.client.get_state(NFL).season

        projections = self.client.get_projections(season, week, league.scoring_format)
        players = self.client.get_players()
        index = self._name_index(projections, players)

        giving, receiving = resolve_sides(proposal, index.lookup)

        rostered = [self._projection_for(pid, projections, players) for pid in roster.player_ids]
        roster_lines = {
            p.name: self._player_line(p) for p in sorted((p for p in rostered if p), key=lambda x: -x.points)
        }

        situation = self._situation(league, roster, league_id, week)
        constraints = (
            f"LINEUP SLOTS: {', '.join(league.starting_slots)}\n"
            "- Only points from the starting lineup score. Bench depth has value only as "
            "insurance or as a future starter."
        )
        prompt = NFL_TRADE_PROMPT.format(
            giving_str="".join(self._player_line(p) for p in giving),
            receiving_str="".join(self._player_line(p) for p in receiving),
            situation=situation,
            constraints=constraints,
            roster_str="".join(roster_lines.values()),
            scoring_label=SCORING_LABELS.get(league.scoring_format, league.scoring_format),
        )
        return SportContext(prompt=prompt, situation=situation, constraints=constraints, roster_lines=roster_lines)

    @staticmethod
    def _name_index(
        projections: dict[str, WeeklyProjection], players: dict[str, PlayerMeta]
    ) -> NameIndex[WeeklyProjection]:
        """Every projectable player, looked up by the name a user would type."""
        index: NameIndex[WeeklyProjection] = NameIndex()
        for projection in projections.values():
            index.add(projection.name, projection)
        # Players with no projection are still tradeable — a bye, or a stash.
        for player_id, meta in players.items():
            name = meta.get("name")
            if name and player_id not in projections and meta.get("position"):
                index.add(name, SleeperNFLProvider._zero_projection(player_id, meta))
        return index

    # ── context ─────────────────────────────────────────────────────

    def _current_week(self) -> int:
        """The week the report is about; the opener while still in preseason."""
        state = self.client.get_state(NFL)
        return max(1, state.week if state.is_regular_season else 1)

    def _week(self, league_id: str) -> _Week:
        """Everything both the header and the prompt are derived from.

        Gathered once because the two would otherwise fetch the same
        projections and re-run the same lineup solve, and could then disagree
        about the totals by a rounding.
        """
        league = self._league(league_id)
        roster = self._my_roster(league_id)
        week, season = self._current_week(), self.client.get_state(NFL).season

        projections = self.client.get_projections(season, week, league.scoring_format)
        players = self.client.get_players()
        projected = [p for p in (self._projection_for(pid, projections, players) for pid in roster.player_ids) if p]

        slots = league.starting_slots
        lineup = current_lineup(slots, roster.starter_ids, projected)
        best = optimal_lineup(slots, projected)
        current_points = round(lineup_points(lineup), 1)
        best_points = round(lineup_points(best), 1)

        return _Week(
            league=league,
            roster=roster,
            week=week,
            season=season,
            projections=projections,
            players=players,
            projected=projected,
            lineup=lineup,
            best=best,
            changes=lineup_changes(slots, roster.starter_ids, projected),
            current_points=current_points,
            best_points=best_points,
            on_bench=round(best_points - current_points, 1),
        )

    def summary(self, league_id: str) -> Summary:
        """The week as it stands: both lineups, the swaps, the byes. No model."""
        state = self._week(league_id)
        _, matchup_stats = self._matchup(state.league, state.roster, league_id, state.week)
        starters = {slot.player.player_id for slot in state.lineup if slot.player}
        # Before the season opens Sleeper publishes no fixtures at all, and
        # flagging every player for having no game turns the page amber over a
        # date rather than a decision. It only means something when others do.
        scheduled = any(p.opponent for p in state.projected)

        return Summary(
            headline=self._headline(state.roster, state.week, state.current_points, state.best_points, state.on_bench)
            + matchup_stats,
            mine=Side(
                name="Your lineup",
                detail=state.roster.record,
                points=f"{state.current_points:.1f} proj",
                lineup=[self._lineup_spot(slot, scheduled) for slot in state.lineup],
                bench=[
                    self._spot(p, scheduled)
                    for p in sorted(
                        (p for p in state.projected if p.player_id not in starters), key=lambda p: -p.points
                    )
                ],
            ),
            opponent=self._opponent(state, league_id, scheduled),
            swaps=[
                Swap(
                    start=f"{change.start.name} ({change.slot})",
                    out=change.bench.name if change.bench else "",
                    gain=f"+{change.gain:.1f} proj pts",
                )
                for change in state.changes
            ],
            fixtures=[
                Stat(label=club, value="no game this week", tone="warning")
                for club in sorted({p.team for p in state.projected if scheduled and not p.opponent})
            ],
        )

    def _opponent(self, state: _Week, league_id: str, scheduled: bool) -> Side | None:
        """The team you are playing, and what they are starting.

        Their lineup is the other half of the only question this week asks, and
        it costs one roster fetch that has already been cached.
        """
        try:
            matchups = self.client.get_matchups(league_id, state.week)
        except SleeperAPIError as e:
            logger.warning(f"Skipping the opponent: {e}")
            return None

        mine = next((m for m in matchups if m.get("roster_id") == state.roster.roster_id), None)
        if not mine or mine.get("matchup_id") is None:
            return None
        theirs = next(
            (
                m
                for m in matchups
                if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != state.roster.roster_id
            ),
            None,
        )
        if not theirs:
            return None

        by_roster = {r.roster_id: r for r in self.client.get_rosters(league_id)}
        roster = by_roster.get(int(theirs.get("roster_id", 0)))
        if roster is None:
            return None

        names = self.client.get_league_users(league_id)
        projected = [
            p for p in (self._projection_for(pid, state.projections, state.players) for pid in roster.player_ids) if p
        ]
        starting = set(roster.starter_ids)
        return Side(
            name=names.get(roster.owner_id, "Opponent"),
            detail=roster.record,
            points=f"{float(theirs.get('points') or 0):.1f}",
            lineup=[self._spot(p, scheduled) for p in projected if p.player_id in starting],
            bench=[self._spot(p, scheduled) for p in projected if p.player_id not in starting],
        )

    def _lineup_spot(self, slot: LineupSlot, scheduled: bool) -> Spot:
        if slot.player is None:
            return Spot(slot=slot.slot, player="—", detail="empty", value="0.0", tone="warning")
        return Spot(
            player_id=slot.player.player_id,
            slot=slot.slot,
            player=slot.player.name,
            detail=self._spot_detail(slot.player, scheduled),
            value=f"{slot.points:.1f}",
            tone=self._spot_tone(slot.player, scheduled),
        )

    def _spot(self, projection: WeeklyProjection, scheduled: bool) -> Spot:
        return Spot(
            player_id=projection.player_id,
            player=projection.name,
            detail=self._spot_detail(projection, scheduled),
            value=f"{projection.points:.1f}",
            tone=self._spot_tone(projection, scheduled),
        )

    @staticmethod
    def _spot_detail(projection: WeeklyProjection, scheduled: bool) -> str:
        if projection.opponent:
            opponent = f"vs {projection.opponent}"
        else:
            opponent = "no game" if scheduled else "not scheduled yet"
        return f"{projection.position} · {projection.team} {opponent}"

    @staticmethod
    def _spot_tone(projection: WeeklyProjection | None, scheduled: bool) -> Tone:
        """A player who will not play is a zero, not a small number.

        Unless nobody is playing, in which case the week simply has not been
        published and there is nothing to notice about any single player.
        """
        if projection is None:
            return "warning"
        if projection.is_questionable:
            return "warning"
        return "warning" if scheduled and not projection.opponent else "neutral"

    def build_context(self, league_id: str) -> SportContext:
        state = self._week(league_id)
        league, roster, week = state.league, state.roster, state.week
        projections, players, projected = state.projections, state.players, state.projected
        lineup, changes = state.lineup, state.changes

        slots = league.starting_slots
        roster_lines = {p.name: self._player_line(p) for p in sorted(projected, key=lambda x: -x.points)}
        starter_ids = {s.player.player_id for s in lineup if s.player}
        lineup_str = "".join(
            f"- {slot.slot}: {slot.player.name} ({slot.player.position}, {slot.player.team}) "
            f"{slot.player.points:.1f} pts vs {slot.player.opponent or 'TBD'}\n"
            if slot.player
            else f"- {slot.slot}: (empty)\n"
            for slot in lineup
        )
        bench_str = "".join(self._player_line(p) for p in projected if p.player_id not in starter_ids) or "- (none)\n"
        changes_str = (
            "".join(
                f"- START {c.start.name} ({c.start.position}) in {c.slot} for "
                f"{c.bench.name if c.bench else 'an empty slot'}: +{c.gain:.1f} projected points\n"
                for c in changes
            )
            or "- None; the current lineup is already the highest-projecting legal one.\n"
        )

        available = self._available_players(league_id, projections, players)
        available_lines = {p.name: self._player_line(p) for p in available}
        trending_str = self._trending(projections, players)

        situation, matchup_stats = self._matchup(league, roster, league_id, week)
        current_points, best_points, on_bench = state.current_points, state.best_points, state.on_bench
        constraints = (
            f"LINEUP SLOTS: {', '.join(slots)}\n"
            f"- Current lineup projects {current_points:.1f} points.\n"
            f"- The best legal lineup projects {best_points:.1f}"
            + (f", so {on_bench:.1f} points are sitting on the bench.\n" if on_bench > 0 else ".\n")
            + "- Bench players score nothing. A start/sit change costs nothing; an add costs a roster spot."
        )

        prompt = NFL_SCOUT_PROMPT.format(
            scoring_label=SCORING_LABELS.get(league.scoring_format, league.scoring_format),
            situation=situation,
            constraints=constraints,
            lineup_str=lineup_str or "- (no lineup set)\n",
            bench_str=bench_str,
            changes_str=changes_str,
            available_str="".join(available_lines.values()) or "- (none available)\n",
            trending_str=trending_str,
        )

        return SportContext(
            prompt=prompt,
            situation=situation,
            constraints=constraints,
            extra=f"LINEUP CHANGES IMPLIED BY PROJECTIONS:\n{changes_str}",
            roster_lines=roster_lines,
            candidate_lines=available_lines,
            headline=self._headline(roster, week, current_points, best_points, on_bench) + matchup_stats,
        )

    @staticmethod
    def _headline(
        roster: SleeperRoster,
        week: int,
        current_points: float,
        best_points: float,
        on_bench: float,
    ) -> list[Stat]:
        """Where this team stands this week, in points.

        Only points sitting on the bench warns: it is the one figure here that
        represents a decision still open rather than a result already in.
        """
        stats = [
            Stat(label="Week", value=str(week)),
            Stat(label="Record", value=roster.record),
            Stat(label="Points for", value=f"{roster.points_for:.1f}"),
            Stat(label="Lineup", value=f"{current_points:.1f}"),
            Stat(label="Best legal", value=f"{best_points:.1f}", tone="good" if on_bench > 0 else "neutral"),
        ]
        if on_bench > 0:
            stats.append(Stat(label="On bench", value=f"+{on_bench:.1f}", tone="warning"))
        return stats

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _zero_projection(player_id: str, meta: PlayerMeta) -> WeeklyProjection:
        """A player with no projection this week: a bye, or inactive."""
        return WeeklyProjection(
            player_id=player_id,
            name=str(meta.get("name") or player_id),
            position=str(meta.get("position") or ""),
            team=str(meta.get("team") or "FA"),
            opponent="",
            points=0.0,
            injury_status=str(meta.get("injury_status") or ""),
        )

    @staticmethod
    def _projection_for(
        player_id: str, projections: dict[str, WeeklyProjection], players: dict[str, PlayerMeta]
    ) -> WeeklyProjection | None:
        """A player's projection, falling back to a zero-point entry.

        A rostered player with no projection is usually on a bye or inactive —
        which is exactly the case the report must see, so they are kept at zero
        rather than dropped from the projected.
        """
        if player_id in projections:
            return projections[player_id]
        meta = players.get(player_id)
        if meta is None:
            return None
        return WeeklyProjection(
            player_id=player_id,
            name=str(meta.get("name") or player_id),
            position=str(meta.get("position") or ""),
            team=str(meta.get("team") or "FA"),
            opponent="",
            points=0.0,
            injury_status=str(meta.get("injury_status") or ""),
        )

    @staticmethod
    def _player_line(p: WeeklyProjection) -> str:
        injury = f" [{p.injury_status}]" if p.is_questionable else ""
        opponent = f" vs {p.opponent}" if p.opponent else " (no game)"
        return f"- {p.name} ({p.position}, {p.team}){injury}{opponent}: {p.points:.1f} proj pts\n"

    def _available_players(
        self, league_id: str, projections: dict[str, WeeklyProjection], players: dict[str, PlayerMeta]
    ) -> list[WeeklyProjection]:
        """Highest-projecting players not rostered anywhere in the league."""
        rostered: set[str] = set()
        for roster in self.client.get_rosters(league_id):
            rostered.update(roster.player_ids)

        free = [p for pid, p in projections.items() if pid not in rostered and p.points > 0]
        return sorted(free, key=lambda p: p.points, reverse=True)[:AVAILABLE_PLAYER_LIMIT]

    def _trending(self, projections: dict[str, WeeklyProjection], players: dict[str, PlayerMeta]) -> str:
        try:
            trending = self.client.get_trending("add", limit=TRENDING_LIMIT)
        except SleeperAPIError as e:
            # An independent signal, not load-bearing — losing it degrades the
            # prompt rather than the report.
            logger.warning(f"Skipping trending players: {e}")
            return "- (unavailable)\n"

        lines = []
        for item in trending:
            meta = players.get(item.player_id)
            name = meta.get("name") if meta else None
            if not name:
                continue
            proj = projections.get(item.player_id)
            points = f"{proj.points:.1f} proj pts" if proj else "no projection"
            lines.append(f"- {name}: added by {item.count:,} managers in 24h, {points}\n")
        return "".join(lines) or "- (none)\n"

    def _situation(
        self,
        league: SleeperLeague,
        roster: SleeperRoster,
        league_id: str,
        week: int,
    ) -> str:
        """The matchup block for the prompt."""
        return self._matchup(league, roster, league_id, week)[0]

    def _matchup(
        self,
        league: SleeperLeague,
        roster: SleeperRoster,
        league_id: str,
        week: int,
    ) -> tuple[str, list[Stat]]:
        """The matchup as prose for the prompt, and as figures for the header.

        Built together because they come from the same three requests; deriving
        them separately would fetch the scoreboard twice for one report.
        """
        header = (
            f"LEAGUE: {league.name} ({league.total_rosters} teams)\n"
            f"WEEK: {week}\nYOUR RECORD: {roster.record}, {roster.points_for:.1f} points for\n"
        )
        try:
            matchups = self.client.get_matchups(league_id, week)
        except SleeperAPIError as e:
            logger.warning(f"No matchup data: {e}")
            return header, []

        mine = next((m for m in matchups if m.get("roster_id") == roster.roster_id), None)
        if not mine or mine.get("matchup_id") is None:
            return header + "No head-to-head matchup this week.\n", []

        opponent = next(
            (
                m
                for m in matchups
                if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != roster.roster_id
            ),
            None,
        )
        if not opponent:
            return header + "No opponent assigned this week.\n", []

        names = self.client.get_league_users(league_id)
        by_roster = {r.roster_id: r for r in self.client.get_rosters(league_id)}
        opp_roster = by_roster.get(int(opponent.get("roster_id", 0)))
        opp_name = names.get(opp_roster.owner_id, "Opponent") if opp_roster else "Opponent"

        mine_points = float(mine.get("points") or 0)
        their_points = float(opponent.get("points") or 0)
        margin = round(mine_points - their_points, 1)

        prose = (
            header
            + f"OPPONENT: {opp_name}"
            + (f" ({opp_roster.record})" if opp_roster else "")
            + f"\nLIVE SCORE: you {mine_points:.1f} - {their_points:.1f} them\n"
        )
        stats = [
            Stat(label="Opponent", value=opp_name + (f" ({opp_roster.record})" if opp_roster else "")),
            Stat(label="Live", value=f"{mine_points:.1f} – {their_points:.1f}"),
            # The only figure here that is a verdict rather than a reading, so
            # it is the only one that takes a tone.
            Stat(
                label="Margin",
                value=f"{margin:+.1f}",
                tone="good" if margin > 0 else "warning" if margin < 0 else "neutral",
            ),
        ]
        return prose, stats
