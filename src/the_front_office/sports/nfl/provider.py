"""NFL on Sleeper.

Points-scoring football: the forward-looking number is Sleeper's own weekly
projection in the league's scoring currency, and the binding constraints are the
starting lineup slots rather than a transaction budget.

Unlike the Yahoo path there is no OAuth — Sleeper's API is public, so a username
is the only configuration.
"""

import logging

from the_front_office.clients.sleeper.client import SleeperClient
from the_front_office.clients.sleeper.types import (
    PlayerMeta,
    Projection,
    SleeperLeague,
    SleeperRoster,
)
from the_front_office.config.constants import FOOTBALL_PROMPT_TEMPLATE
from the_front_office.config.settings import settings
from the_front_office.exceptions import LeagueNotFoundError, SleeperAPIError
from the_front_office.report.types import SportContext
from the_front_office.sports.base import LeagueRef
from the_front_office.sports.nfl.lineup import (
    current_lineup,
    lineup_changes,
    lineup_points,
    optimal_lineup,
)

logger = logging.getLogger(__name__)

SCORING_LABELS = {
    "pts_ppr": "Full PPR (1 point per reception)",
    "pts_half_ppr": "Half PPR (0.5 per reception)",
    "pts_std": "Standard (no point per reception)",
}

AVAILABLE_PLAYER_LIMIT = 25
TRENDING_LIMIT = 10


class NFLProvider:
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

    # ── context ─────────────────────────────────────────────────────

    def build_context(self, league_id: str) -> SportContext:
        league = self._league(league_id)
        roster = self._my_roster(league_id)
        state = self.client.get_nfl_state()

        # In the preseason, project the opening week rather than week 0.
        week = max(1, state.week if state.is_regular_season else 1)
        season = state.season

        projections = self.client.get_projections(season, week, league.scoring_format)
        players = self.client.get_players()

        squad = [self._projection_for(pid, projections, players) for pid in roster.player_ids]
        squad = [p for p in squad if p is not None]  # type: ignore[misc]

        slots = league.starting_slots
        # What is set now, versus the best legal lineup. Showing the optimal one
        # as "your lineup" would put the same player in both the lineup and the
        # bench list, which is how the model gets told to start someone twice.
        lineup = current_lineup(slots, roster.starter_ids, squad)  # type: ignore[arg-type]
        best = optimal_lineup(slots, squad)  # type: ignore[arg-type]
        changes = lineup_changes(slots, roster.starter_ids, squad)  # type: ignore[arg-type]

        squad_lines = {
            p.name: self._player_line(p)
            for p in sorted(squad, key=lambda x: -x.points)  # type: ignore[union-attr]
        }
        starter_ids = {s.player.player_id for s in lineup if s.player}
        lineup_str = "".join(
            f"- {slot.slot}: {slot.player.name} ({slot.player.position}, {slot.player.team}) "
            f"{slot.player.points:.1f} pts vs {slot.player.opponent or 'TBD'}\n"
            if slot.player
            else f"- {slot.slot}: (empty)\n"
            for slot in lineup
        )
        bench_str = (
            "".join(self._player_line(p) for p in squad if p.player_id not in starter_ids)  # type: ignore[union-attr]
            or "- (none)\n"
        )
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

        situation = self._situation(league, roster, league_id, week)
        # Derive the gap from the same rounded figures that are printed, or the
        # prompt contradicts itself: 124.1 - 121.4 shown alongside a 2.8 delta.
        current_points = round(lineup_points(lineup), 1)
        best_points = round(lineup_points(best), 1)
        on_bench = round(best_points - current_points, 1)
        constraints = (
            f"LINEUP SLOTS: {', '.join(slots)}\n"
            f"- Current lineup projects {current_points:.1f} points.\n"
            f"- The best legal lineup projects {best_points:.1f}"
            + (f", so {on_bench:.1f} points are sitting on the bench.\n" if on_bench > 0 else ".\n")
            + "- Bench players score nothing. A start/sit change costs nothing; an add costs a roster spot."
        )

        prompt = FOOTBALL_PROMPT_TEMPLATE.format(
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
            squad_lines=squad_lines,
            candidate_lines=available_lines,
        )

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _projection_for(
        player_id: str, projections: dict[str, Projection], players: dict[str, PlayerMeta]
    ) -> Projection | None:
        """A player's projection, falling back to a zero-point entry.

        A rostered player with no projection is usually on a bye or inactive —
        which is exactly the case the report must see, so they are kept at zero
        rather than dropped from the squad.
        """
        if player_id in projections:
            return projections[player_id]
        meta = players.get(player_id)
        if meta is None:
            return None
        return Projection(
            player_id=player_id,
            name=str(meta.get("name") or player_id),
            position=str(meta.get("position") or ""),
            team=str(meta.get("team") or "FA"),
            opponent="",
            points=0.0,
            injury_status=str(meta.get("injury_status") or ""),
        )

    @staticmethod
    def _player_line(p: Projection) -> str:
        injury = f" [{p.injury_status}]" if p.is_questionable else ""
        opponent = f" vs {p.opponent}" if p.opponent else " (no game)"
        return f"- {p.name} ({p.position}, {p.team}){injury}{opponent}: {p.points:.1f} proj pts\n"

    def _available_players(
        self, league_id: str, projections: dict[str, Projection], players: dict[str, PlayerMeta]
    ) -> list[Projection]:
        """Highest-projecting players not rostered anywhere in the league."""
        rostered: set[str] = set()
        for roster in self.client.get_rosters(league_id):
            rostered.update(roster.player_ids)

        free = [p for pid, p in projections.items() if pid not in rostered and p.points > 0]
        return sorted(free, key=lambda p: p.points, reverse=True)[:AVAILABLE_PLAYER_LIMIT]

    def _trending(self, projections: dict[str, Projection], players: dict[str, PlayerMeta]) -> str:
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
        """The matchup block: opponent, record, and projected margin."""
        header = (
            f"LEAGUE: {league.name} ({league.total_rosters} teams)\n"
            f"WEEK: {week}\nYOUR RECORD: {roster.record}, {roster.points_for:.1f} points for\n"
        )
        try:
            matchups = self.client.get_matchups(league_id, week)
        except SleeperAPIError as e:
            logger.warning(f"No matchup data: {e}")
            return header

        mine = next((m for m in matchups if m.get("roster_id") == roster.roster_id), None)
        if not mine or mine.get("matchup_id") is None:
            return header + "No head-to-head matchup this week.\n"

        opponent = next(
            (
                m
                for m in matchups
                if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != roster.roster_id
            ),
            None,
        )
        if not opponent:
            return header + "No opponent assigned this week.\n"

        names = self.client.get_league_users(league_id)
        by_roster = {r.roster_id: r for r in self.client.get_rosters(league_id)}
        opp_roster = by_roster.get(int(opponent.get("roster_id", 0)))
        opp_name = names.get(opp_roster.owner_id, "Opponent") if opp_roster else "Opponent"

        return (
            header
            + f"OPPONENT: {opp_name}"
            + (f" ({opp_roster.record})" if opp_roster else "")
            + f"\nLIVE SCORE: you {float(mine.get('points') or 0):.1f} - "
            f"{float(opponent.get('points') or 0):.1f} them\n"
        )
