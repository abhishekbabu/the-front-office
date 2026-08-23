"""NFL on Sleeper.

Points-scoring football: the forward-looking number is Sleeper's own weekly
projection in the league's scoring currency, and the binding constraints are the
starting lineup slots rather than a transaction budget.

Unlike the Yahoo path there is no OAuth — Sleeper's API is public, so a username
is the only configuration.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from the_front_office.adapters.outbound.platforms.sleeper.client import NFL, SleeperClient
from the_front_office.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    ScheduledGame,
    SleeperLeague,
    SleeperRoster,
    Transaction,
    WeeklyProjection,
)
from the_front_office.adapters.outbound.sports.dates import day_month, weekday_day_month
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
    ActivityRow,
    LeagueSchedule,
    Match,
    PlayerCard,
    PlayerDetail,
    ScheduleRow,
    Side,
    SportContext,
    Spot,
    StandingRow,
    Stat,
    StatGroup,
    Summary,
    Swap,
    Tone,
    TradeProposal,
)
from the_front_office.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# Sleeper's projection keys, in the order a box score reads them. Only the ones
# a fantasy line is actually made of — the payload carries dozens more, most of
# which are zero for any given player.
PROJECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("pass_att", "Pass att"),
    ("pass_cmp", "Completions"),
    ("pass_yd", "Pass yards"),
    ("pass_td", "Pass TD"),
    ("pass_int", "Interceptions"),
    ("rush_att", "Carries"),
    ("rush_yd", "Rush yards"),
    ("rush_td", "Rush TD"),
    ("rec_tgt", "Targets"),
    ("rec", "Receptions"),
    ("rec_yd", "Rec yards"),
    ("rec_td", "Rec TD"),
    ("fum_lost", "Fumbles lost"),
)


def _projection_lines(stats: dict[str, float]) -> list[Stat]:
    """The projection broken out, skipping what does not apply.

    A receiver has no passing line, and printing a column of zeroes for one
    buries the three numbers that matter.
    """
    return [
        Stat(label=label, value=f"{stats[key]:.1f}".rstrip("0").rstrip(".") or "0")
        for key, label in PROJECTION_LABELS
        if stats.get(key)
    ]


@dataclass(frozen=True)
class _Live:
    """The week as it has actually gone, so far.

    Zero points is ambiguous on its own — a receiver who dropped everything and
    a receiver whose game is on Monday both sit at nought — so the real-world
    schedule decides which of the two a row is showing.
    """

    started: set[str]
    """Clubs whose real-world game has kicked off."""

    points: dict[str, float]
    """What each player has scored, keyed by Sleeper's player_id."""

    def scored(self, player_id: str, team: str) -> float | None:
        """Points where that club's game has started, and nothing before it."""
        if not self.under_way or team not in self.started:
            return None
        return self.points.get(player_id)

    @property
    def under_way(self) -> bool:
        """Both halves are required. Kickoffs with no scoreboard behind them
        would render every row as nought — a whole team that blanked, rather
        than a request that failed."""
        return bool(self.started) and bool(self.points)


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

# Sleeper serves portraits off its own CDN, keyed by the same player_id the
# rest of the API uses, with no key and no lookup.
PORTRAIT_URL = "https://sleepercdn.com/content/nfl/players/{player_id}.jpg"

SPLIT_LABELS = (
    ("pass_yd", "Passing yards"),
    ("pass_td", "Passing TDs"),
    ("pass_int", "Interceptions"),
    ("cmp_pct", "Completion %"),
    ("rush_yd", "Rushing yards"),
    ("rush_td", "Rushing TDs"),
    ("rec", "Receptions"),
    ("rec_tgt", "Targets"),
    ("rec_yd", "Receiving yards"),
    ("rec_td", "Receiving TDs"),
)


def _split_lines(splits: dict[str, float]) -> list[Stat]:
    """The production behind the total, skipping what a position never does.

    A quarterback with one reception for minus ten yards is noise, and a
    running back has no completion percentage at all.
    """
    return [
        Stat(label=label, value=f"{splits[key]:.0f}" if key != "cmp_pct" else f"{splits[key]:.1f}%")
        for key, label in SPLIT_LABELS
        if splits.get(key)
    ]


def _date(iso: str) -> date | None:
    """Sleeper publishes a day, not an instant, so this is a label not a time."""
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _day(iso: str) -> str:
    """One date, as a person reads it: 'Sun 13 Sep'."""
    parsed = _date(iso)
    return weekday_day_month(parsed) if parsed else ""


def _week_dates(games: list[ScheduledGame]) -> str:
    """The span a fantasy week actually covers.

    An NFL week runs Thursday to Monday, so one date would be wrong for most
    of it and a range is what somebody is checking against their own calendar.
    """
    days = sorted({d for d in (_date(g.date) for g in games) if d})
    if not days:
        return ""
    if days[0] == days[-1]:
        return day_month(days[0])
    if days[0].month == days[-1].month:
        return f"{days[0].day}-{day_month(days[-1])}"
    return f"{day_month(days[0])} - {day_month(days[-1])}"


def _moment(epoch_ms: int) -> str:
    """Sleeper timestamps transactions in epoch milliseconds.

    Rendered in UTC rather than the machine's zone: it is a label on a list,
    and a league spans zones anyway.
    """
    if not epoch_ms:
        return ""
    return day_month(datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc))


# A week made and a week wasted, on a points-league scale where a startable
# flex is worth around ten.
HAUL_POINTS = 20.0
BLANK_POINTS = 5.0

REGULAR_SEASON_WEEKS = 18
# "What did I miss", not the season's whole transaction log.
ACTIVITY_WEEKS = 3

TRANSACTION_LABELS = {
    "waiver": "Waiver",
    "free_agent": "Free agent",
    "trade": "Trade",
    "commissioner": "Commissioner",
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
        """One player: the week, what makes the projection, and who they are."""
        state = self._week(league_id)
        meta = state.players.get(player_id)
        if meta is None:
            raise PlayerNotFoundError([player_id])

        projection = state.projections.get(player_id)
        scheduled = any(p.opponent for p in state.projected)
        depth = int(meta.get("depth_chart_order") or 0)
        injury = str(meta.get("injury_status") or "")
        body = str(meta.get("injury_body_part") or "")

        groups = [
            StatGroup(
                title=f"Week {state.week}",
                stats=[
                    Stat(label="Opponent", value=self._opponent_label(projection, scheduled)),
                    Stat(label="Projected", value=f"{projection.points:.1f}" if projection else "—"),
                    Stat(
                        label="Status",
                        value=injury or "active",
                        tone="warning" if injury else "good",
                    ),
                    *([Stat(label="Injury", value=body)] if body else []),
                ],
            )
        ]
        if projection and projection.stats:
            groups.append(StatGroup(title="Projected line", stats=_projection_lines(projection.stats)))
        groups.extend(self._past_seasons(player_id, state))
        groups.append(
            StatGroup(
                title="Player",
                stats=[
                    Stat(label="Depth chart", value=f"{depth}" if depth else "unlisted"),
                    Stat(label="Experience", value=f"{int(meta.get('years_exp') or 0)} seasons"),
                    *([Stat(label="Age", value=str(meta["age"]))] if meta.get("age") else []),
                    *([Stat(label="Number", value=f"#{meta['number']}")] if meta.get("number") else []),
                    *([Stat(label="College", value=str(meta["college"]))] if meta.get("college") else []),
                ],
            )
        )

        return PlayerDetail(
            player_id=player_id,
            name=str(meta.get("name") or player_id),
            position=str(meta.get("position") or ""),
            team=str(meta.get("team") or "FA"),
            headline=f"{projection.points:.1f} proj pts" if projection else "no projection",
            note=str(meta.get("injury_notes") or injury),
            image_url=PORTRAIT_URL.format(player_id=player_id),
            tone="warning" if injury else "neutral",
            groups=groups,
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
        live = self._live(state, league_id)
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
                points=self._side_total(state, live),
                lineup=[self._lineup_spot(slot, scheduled, live) for slot in state.lineup],
                bench=[
                    self._spot(p, scheduled, live=live)
                    for p in sorted(
                        (p for p in state.projected if p.player_id not in starters), key=lambda p: -p.points
                    )
                ],
            ),
            opponent=self._opponent(state, league_id, scheduled, live),
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
            window=self._window(state),
        )

    def _window(self, state: _Week) -> str:
        """Which week, and when it is actually played.

        A week with no dates on it is a number, and the number is the one thing
        somebody already knows.
        """
        span = _week_dates(self._games_by_week(state.season).get(state.week, []))
        return f"Week {state.week} · {span}" if span else f"Week {state.week}"

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The season, the table, this week's real games, and what the league did."""
        state = self._week(league_id)
        rosters = self.client.get_rosters(league_id)
        names = self.client.get_league_users(league_id)
        by_roster = {r.roster_id: r for r in rosters}

        return LeagueSchedule(
            season=self._season_rows(state, league_id, by_roster, names),
            standings=self._standings(state, rosters, names),
            matches=self._matches(state),
            activity=self._activity(state, league_id, by_roster, names),
        )

    def _season_rows(
        self,
        state: _Week,
        league_id: str,
        by_roster: dict[int, SleeperRoster],
        names: dict[str, str],
    ) -> list[ScheduleRow]:
        """Your own season, week by week, with who you play and how it went.

        Eighteen matchup fetches, run concurrently and cached — and the reason
        this is a separate call from the week rather than something the week
        carries, since nobody checking a lineup should wait on the season.
        """
        games = self._games_by_week(state.season)
        weeks = list(range(1, REGULAR_SEASON_WEEKS + 1))
        try:
            by_week = self.client.get_matchups_bulk(league_id, weeks)
        except SleeperAPIError as e:
            logger.warning(f"Continuing without the season's matchups: {e}")
            by_week = {}

        rows: list[ScheduleRow] = []
        for week in weeks:
            matchups = by_week.get(week, [])
            mine = next((m for m in matchups if m.get("roster_id") == state.roster.roster_id), None)
            theirs = self._other_side(matchups, mine, state.roster.roster_id)
            opponent = by_roster.get(int(theirs.get("roster_id", 0))) if theirs else None

            rows.append(
                ScheduleRow(
                    label=f"Week {week}",
                    date=_week_dates(games.get(week, [])),
                    opponent=names.get(opponent.owner_id, "") if opponent else "",
                    detail=opponent.record if opponent else "bye",
                    result=self._result(mine, theirs, week, state.week),
                    tone=self._week_tone(mine, theirs, week, state.week),
                    is_current=week == state.week,
                )
            )
        return rows

    @staticmethod
    def _other_side(matchups: list[dict[str, Any]], mine: dict[str, Any] | None, roster_id: int) -> Any:
        if not mine or mine.get("matchup_id") is None:
            return None
        return next(
            (m for m in matchups if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != roster_id),
            None,
        )

    @staticmethod
    def _result(mine: Any, theirs: Any, week: int, current: int) -> str:
        """The score, and only once there is one. A future week is not 0-0."""
        if week >= current or not mine or not theirs:
            return ""
        return f"{float(mine.get('points') or 0):.1f}-{float(theirs.get('points') or 0):.1f}"

    @staticmethod
    def _week_tone(mine: Any, theirs: Any, week: int, current: int) -> Tone:
        if week >= current or not mine or not theirs:
            return "neutral"
        return "good" if float(mine.get("points") or 0) > float(theirs.get("points") or 0) else "warning"

    def _standings(self, state: _Week, rosters: list[SleeperRoster], names: dict[str, str]) -> list[StandingRow]:
        """The table, sorted the way the league is: record first, then points."""
        ordered = sorted(rosters, key=lambda r: (-(r.wins), -(r.points_for)))
        return [
            StandingRow(
                rank=i,
                name=names.get(r.owner_id, f"Roster {r.roster_id}"),
                record=r.record,
                points=f"{r.points_for:.1f}",
                is_mine=r.roster_id == state.roster.roster_id,
            )
            for i, r in enumerate(ordered, start=1)
        ]

    def _matches(self, state: _Week) -> list[Match]:
        """The real games this fantasy week is made of.

        Only the ones your league is actually exposed to would be a smaller
        list, but which clubs matter changes with every waiver — the whole
        slate is what a week is, and it is one cached request.
        """
        games = self._games_by_week(state.season).get(state.week, [])
        mine = {p.team for p in state.projected}
        return [
            Match(
                label=_day(g.date),
                home=g.home,
                away=g.away,
                # Whether you have anyone in it, which is the only thing that
                # makes one game on a Sunday slate different from another.
                detail="you have players" if {g.home, g.away} & mine else "",
                tone="good" if {g.home, g.away} & mine else "neutral",
            )
            for g in games
        ]

    def _activity(
        self,
        state: _Week,
        league_id: str,
        by_roster: dict[int, SleeperRoster],
        names: dict[str, str],
    ) -> list[ActivityRow]:
        """What the league has done lately, newest first.

        Bounded to the last few weeks rather than the season: this is "what did
        I miss", and a hundred rows of September waivers is not that.
        """
        dated: list[tuple[int, ActivityRow]] = []
        for week in range(max(1, state.week - ACTIVITY_WEEKS + 1), state.week + 1):
            try:
                transactions = self.client.get_transactions(league_id, week)
            except SleeperAPIError as e:
                logger.warning(f"Skipping week {week} activity: {e}")
                continue
            dated.extend(self._activity_rows(transactions, state, by_roster, names))
        # Sorted on the instant, not on the string that renders it: "Sep 3"
        # sorts before "Sep 21" alphabetically and after it in time.
        return [row for _, row in sorted(dated, key=lambda pair: pair[0], reverse=True)]

    def _activity_rows(
        self,
        transactions: list[Transaction],
        state: _Week,
        by_roster: dict[int, SleeperRoster],
        names: dict[str, str],
    ) -> list[tuple[int, ActivityRow]]:
        rows: list[tuple[int, ActivityRow]] = []
        for t in transactions:
            roster = by_roster.get(t.roster_ids[0]) if t.roster_ids else None
            moved = [f"+{self._name_of(pid, state)}" for pid in t.adds] + [
                f"-{self._name_of(pid, state)}" for pid in t.drops
            ]
            rows.append(
                (
                    t.when,
                    ActivityRow(
                        when=_moment(t.when),
                        who=names.get(roster.owner_id, "") if roster else "",
                        what=TRANSACTION_LABELS.get(t.kind, t.kind),
                        detail=", ".join(moved),
                        tone="good" if roster and roster.roster_id == state.roster.roster_id else "neutral",
                    ),
                )
            )
        return rows

    @staticmethod
    def _name_of(player_id: str, state: _Week) -> str:
        meta = state.players.get(player_id)
        return str(meta.get("name") or player_id) if meta else player_id

    def _games_by_week(self, season: str) -> dict[int, list[ScheduledGame]]:
        """The season schedule bucketed by week, or nothing if it will not load.

        Dates are enrichment: a week without them is still a week.
        """
        try:
            games = self.client.get_season_schedule(season)
        except SleeperAPIError as e:
            logger.warning(f"Continuing without schedule dates: {e}")
            return {}
        by_week: dict[int, list[ScheduledGame]] = {}
        for g in games:
            by_week.setdefault(g.week, []).append(g)
        return by_week

    def _live(self, state: _Week, league_id: str) -> _Live:
        """What has actually been scored, and whose clubs have kicked off."""
        started = {
            club
            for game in self._games_by_week(state.season).get(state.week, [])
            if game.status and game.status != "pre_game"
            for club in (game.home, game.away)
        }
        try:
            matchups = self.client.get_matchups(league_id, state.week)
        except SleeperAPIError as e:
            logger.warning(f"Continuing without live scores: {e}")
            return _Live(started=started, points={})

        points: dict[str, float] = {}
        for entry in matchups:
            for player_id, scored in (entry.get("players_points") or {}).items():
                points[str(player_id)] = float(scored or 0)
        return _Live(started=started, points=points)

    @staticmethod
    def _side_total(state: _Week, live: _Live) -> str:
        """The projection until the ball is rolling, then what is on the board."""
        if not live.under_way:
            return f"{state.current_points:.1f} proj"
        scored = sum(live.scored(slot.player.player_id, slot.player.team) or 0 for slot in state.lineup if slot.player)
        return f"{scored:.1f} pts"

    def _opponent(self, state: _Week, league_id: str, scheduled: bool, live: _Live) -> Side | None:
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
        by_id = {p.player_id: p for p in projected}

        # Walked in slot order rather than filtered out of `player_ids`, which
        # Sleeper returns in no order at all. Both sides are read across, so an
        # opponent listed QB-first against your kicker is not a comparison.
        # `starter_ids` is positionally aligned with the league's starting
        # slots, which is the only thing that makes the two columns rows.
        slots = state.league.starting_slots
        if len(roster.starter_ids) == len(slots):
            lineup = [
                self._spot(by_id[pid], scheduled, slot=slot, live=live)
                if pid in by_id
                else Spot(slot=slot, player="—", detail="empty", value="0.0", tone="warning")
                for slot, pid in zip(slots, roster.starter_ids, strict=True)
            ]
        else:
            # Off-length means the positions cannot be trusted, and a WR
            # labelled QB is worse than a row carrying no label at all.
            logger.warning(f"Roster {roster.roster_id} starts {len(roster.starter_ids)} into {len(slots)} slots")
            lineup = [self._spot(p, scheduled, live=live) for p in projected if p.player_id in starting]
        return Side(
            name=names.get(roster.owner_id, "Opponent"),
            detail=roster.record,
            points=f"{float(theirs.get('points') or 0):.1f}",
            lineup=lineup,
            bench=[self._spot(p, scheduled, live=live) for p in projected if p.player_id not in starting],
        )

    def _past_seasons(self, player_id: str, state: _Week) -> list[StatGroup]:
        """What this player has actually done, most recent season first.

        A projection is a guess; these are the seasons it is a guess about, and
        a page that shows only the guess gives no way to weigh it. Per game
        rather than total, because a total mostly measures availability.

        Degrades to nothing: a rookie has no history, and neither does a season
        Sleeper has not published, which is not a reason to fail the page.
        """
        scoring = state.league.scoring_format
        groups: list[StatGroup] = []
        for season in self._recent_seasons(state.season):
            try:
                stats = self.client.get_season_stats(season).get(player_id)
            except SleeperAPIError as e:
                logger.warning(f"Skipping {season} totals: {e}")
                continue
            if stats is None or not stats.games:
                continue
            groups.append(
                StatGroup(
                    title=f"{season} season",
                    stats=[
                        Stat(label="Per game", value=f"{stats.per_game(scoring):.1f}"),
                        Stat(label="Total", value=f"{stats.scored(scoring):.1f}"),
                        Stat(label="Games", value=str(stats.games)),
                        *(
                            [Stat(label="Position rank", value=f"#{stats.position_rank}")]
                            if stats.position_rank
                            else []
                        ),
                        *_split_lines(stats.splits),
                    ],
                )
            )
        return groups

    @staticmethod
    def _recent_seasons(season: str) -> list[str]:
        """The two seasons before this one, newest first.

        Two rather than a career: three years back is a different team, a
        different scheme and usually a different player.
        """
        try:
            year = int(season)
        except ValueError:
            return []
        return [str(year - 1), str(year - 2)]

    def _lineup_spot(self, slot: LineupSlot, scheduled: bool, live: _Live | None = None) -> Spot:
        if slot.player is None:
            return Spot(slot=slot.slot, player="—", detail="empty", value="0.0", tone="warning")
        return self._spot(slot.player, scheduled, slot=slot.slot, live=live, projected=slot.points)

    def _spot(
        self,
        projection: WeeklyProjection,
        scheduled: bool,
        slot: str = "",
        live: _Live | None = None,
        projected: float | None = None,
    ) -> Spot:
        """One row, showing what happened where the game has started.

        Once a club has kicked off, what its players actually scored is the
        number somebody is looking for, and the projection beside it is a guess
        about a question already being answered.
        """
        scored = live.scored(projection.player_id, projection.team) if live else None
        points = projection.points if projected is None else projected
        return Spot(
            player_id=projection.player_id,
            slot=slot,
            player=projection.name,
            detail=self._spot_detail(projection, scheduled, slot),
            value=f"{scored:.1f} pts" if scored is not None else f"{points:.1f}",
            tone=self._live_tone(scored) if scored is not None else self._spot_tone(projection, scheduled),
        )

    @staticmethod
    def _live_tone(scored: float) -> Tone:
        """A game already played answers its own question: a doubt about
        somebody who has been on the field is no longer a doubt."""
        if scored >= HAUL_POINTS:
            return "good"
        return "warning" if scored <= BLANK_POINTS else "neutral"

    @staticmethod
    def _spot_detail(projection: WeeklyProjection, scheduled: bool, slot: str = "") -> str:
        if projection.opponent:
            opponent = f"vs {projection.opponent}"
        else:
            opponent = "no game" if scheduled else "not scheduled yet"
        # The slot column already says "QB", so repeating it here reads as two
        # different facts about one row. A FLEX is the case worth keeping: the
        # place and the position genuinely differ, and which of them is filling
        # it is the whole question the row is asking.
        if projection.position == slot:
            return f"{projection.team} {opponent}"
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
