"""Fantasy Premier League on the official game.

The only sport here whose league platform is also its stats provider: the same
payload that lists a squad carries expected goals, ownership and the game's own
next-gameweek projection, so there is no second platform to join names against.

What binds a decision is money and a transfer allowance rather than a waiver
budget or a set of lineup slots, and the highest-leverage call of the week is
the captaincy — which is why the report leads with it.

There is no trade path. FPL managers do not exchange players with each other;
the equivalent action is a transfer against the market, which the scouting
report already recommends.
"""

import logging
from collections.abc import Callable
from datetime import datetime

from the_front_office.adapters.outbound.platforms.fpl.client import FPLClient, free_transfers
from the_front_office.adapters.outbound.platforms.fpl.types import (
    TRANSFER_HIT,
    Entry,
    Gameweek,
    H2HMatch,
    LiveStat,
    MiniLeague,
    PastSeason,
    Player,
    Squad,
    as_millions,
)
from the_front_office.adapters.outbound.sports.dates import at_time
from the_front_office.adapters.outbound.sports.fpl.squad import (
    Lineup,
    LineupChange,
    Transfer,
    affordable_transfers,
    best_lineup,
    effective_points,
    lineup_changes,
    points_with_captain,
)
from the_front_office.config.constants import FPL_SCOUT_PROMPT
from the_front_office.config.settings import settings
from the_front_office.domain.errors import (
    FPLAPIError,
    LeagueNotFoundError,
    PlayerNotFoundError,
    TeamNotFoundError,
)
from the_front_office.domain.models import (
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
    StatRow,
    StatTable,
    Summary,
    Swap,
    TeamRef,
    Tone,
)
from the_front_office.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

# FPL's own player pages show a portrait keyed by Opta's code, not the element
# id. Public, keyless, and already alongside every other asset the site serves.
PORTRAIT_URL = "https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png"

# Three back is a different club and usually a different role; a fourth row
# adds scrolling rather than judgement.
# Two back plus the one in progress is three columns, which fits a drawer and
# is as far as a player's form is still the same player.
PAST_SEASON_LIMIT = 2

# A period with no answer at all, distinct from a nought, which is an answer.
NOT_APPLICABLE = "N/A"

# FPL's own scale runs 1-5; 4 is where its UI starts calling a run hard.
HARD_FIXTURE = 4

# What counts as a return and what counts as nothing, on FPL's own scale: two
# points is an appearance and no more, and a double-figure haul is a week made.
HAUL = 10
BLANK = 2

MARKET_LIMIT = 20

# Enough to find a transfer, few enough to read. The prompt's own shortlist is
# far shorter; this is a list somebody scrolls.
MARKET_BROWSE_LIMIT = 100
"""Top available players shown per report, across all positions."""

TRANSFER_LIMIT = 10


class FPLProvider:
    """SportProvider for the official Fantasy Premier League game.

    Named for neither a separate platform nor a separate sport because there is
    only one of each: the game is both.
    """

    sport = "fpl"
    label = "FPL (Fantasy Premier League)"

    def __init__(self, entry_id: int | None = None, *, client: FPLClient | None = None):
        self.entry_id = entry_id if entry_id is not None else settings.fpl_entry_id
        self.client = client or FPLClient()

    def _resolve_entry_id(self) -> int:
        if not self.entry_id:
            raise LeagueNotFoundError("FPL_ENTRY_ID is not set in .env")
        return self.entry_id

    # ── leagues ─────────────────────────────────────────────────────

    def list_leagues(self) -> list[LeagueRef]:
        """The manager's invitational mini-leagues.

        The game's own leagues — Overall, your country, one per gameweek — are
        filtered out. Everyone is in them, nobody competes in them, and a report
        per gameweek league would mean 38 identical reports.

        Falls back to the overall standing when the manager has joined no
        private league, so a brand-new account still has something to scout.
        """
        entry = self.client.get_entry(self._resolve_entry_id())
        private = [lg for lg in entry.leagues if lg.is_private]
        if not private:
            return [
                LeagueRef(
                    league_id=str(entry.entry_id),
                    name=entry.name,
                    sport=self.sport,
                    detail=f"overall rank {entry.overall_rank:,} · {entry.overall_points} pts",
                )
            ]
        return [
            LeagueRef(
                league_id=str(lg.id),
                name=lg.name,
                sport=self.sport,
                detail=f"{lg.standing} · {entry.name}",
            )
            for lg in private
        ]

    # ── squad ───────────────────────────────────────────────────────

    def _last_completed_gameweek(self, upcoming: int) -> int:
        """The most recent gameweek whose picks the game has published.

        Picks appear only after a deadline passes, so before the season opens
        there is nothing to read and the report cannot be built.
        """
        if upcoming <= 1:
            raise FPLAPIError("The season has not started, so no squad has been picked yet.")
        return upcoming - 1

    def _squad(self, entry_id: int, gameweek: int) -> tuple[Squad, list[Player], list[Player], list[Player]]:
        """The squad, all fifteen, and the eleven and four as the manager set them.

        Starters and bench come back in pick order, not in expected-points
        order: the bench order is itself a decision, since auto-subs come on in
        the order the manager listed them.
        """
        squad = self.client.get_squad(entry_id, gameweek)
        catalog = self.client.get_players()
        in_order = [(pick, catalog[pick.element]) for pick in squad.picks if pick.element in catalog]
        in_order.sort(key=lambda pair: pair[0].position)
        return (
            squad,
            [player for _, player in in_order],
            [player for pick, player in in_order if pick.is_starting],
            [player for pick, player in in_order if not pick.is_starting],
        )

    def player(self, league_id: str, player_id: str) -> PlayerDetail:
        """One player, grouped the way a manager actually weighs them.

        Everything here comes from the catalog every other call already reads,
        so depth costs nothing: Opta's expected numbers, the season return, the
        set-piece duty that separates a good price from a bad one, and the
        market moving under the price.
        """
        catalog = self.client.get_players()
        player = catalog.get(int(player_id)) if player_id.isdigit() else None
        if player is None:
            raise PlayerNotFoundError([player_id])

        upcoming = self.client.upcoming_gameweek()

        return PlayerDetail(
            player_id=str(player.id),
            name=player.full_name or player.name,
            position=player.position,
            team=player.team,
            headline=f"{player.expected_points:.1f}",
            headline_label=f"xPts for {upcoming.name}",
            note=player.news,
            image_url=PORTRAIT_URL.format(code=player.code) if player.code else "",
            tone="warning" if player.availability else "neutral",
            groups=[
                StatGroup(
                    title="This week",
                    stats=[
                        Stat(label="Fixture", value=self._fixture_line(player, upcoming.id)),
                        Stat(label="Expected", value=f"{player.expected_points:.1f} xPts"),
                        Stat(label="Form", value=f"{player.form:.1f}"),
                        Stat(
                            label="Availability",
                            value=player.availability or "fit",
                            tone="warning" if player.availability else "good",
                        ),
                    ],
                ),
                StatGroup(
                    title="Underlying",
                    stats=[
                        Stat(label="xG", value=f"{player.expected_goals:.2f}"),
                        Stat(label="xA", value=f"{player.expected_assists:.2f}"),
                        Stat(label="xGI", value=f"{player.expected_goal_involvements:.2f}"),
                        Stat(label="xGC", value=f"{player.expected_goals_conceded:.2f}"),
                        Stat(label="ICT", value=f"{player.ict_index:.1f}"),
                    ],
                ),
                StatGroup(title="Set pieces", stats=self._set_pieces(player)),
                StatGroup(
                    title="Market",
                    stats=[
                        Stat(label="Price", value=as_millions(player.cost)),
                        Stat(
                            label="This week",
                            value=f"{'+' if player.price_change > 0 else ''}{player.price_change / 10:.1f}m",
                            tone="good" if player.price_change > 0 else "neutral",
                        ),
                        Stat(label="Owned by", value=f"{player.selected_by:.1f}%"),
                        Stat(label="Transfers in", value=f"{player.transfers_in:,}"),
                        Stat(label="Transfers out", value=f"{player.transfers_out:,}"),
                    ],
                ),
            ],
            tables=[table] if (table := self._season_table(player)) else [],
        )

    def _season_table(self, player: Player) -> StatTable | None:
        """This season beside the two before it, read across rather than down.

        The catalog carries only the season in progress, which in August is a
        single gameweek — so a page meant to justify a £15m striker shows one
        match, and the question anybody actually has is whether he did it last
        year. Stacked groups make you hold last year's goals in your head while
        scrolling to this year's; a row puts them side by side.

        Costs one request, made only when somebody opens a player, and degrades
        to the current season alone rather than failing: a promoted club's
        signing has no FPL history at all.
        """
        try:
            past = self.client.get_past_seasons(player.id)
        except FPLAPIError as e:
            logger.warning(f"Skipping past seasons for {player.name}: {e}")
            past = []

        seasons = list(reversed(past[-PAST_SEASON_LIMIT:]))
        columns = [self._season_label(seasons)] + [s.season for s in seasons]

        # A season nobody has kicked a ball in has no answers, and a column of
        # noughts claims it does.
        started = self._season_started()
        keeper_or_defender = player.position in ("GKP", "DEF")

        def row(label: str, current: str, of_past: Callable[[PastSeason], str], tone: Tone = "neutral") -> StatRow:
            return StatRow(
                label=label,
                values=[current if started else NOT_APPLICABLE] + [of_past(s) for s in seasons],
                tone=tone,
            )

        rows = [
            row("Points", str(player.total_points), lambda s: str(s.total_points)),
            row("Per start", f"{player.points_per_game:.1f}", lambda s: f"{s.points_per_game:.1f}"),
            row("Starts", str(player.starts), lambda s: str(s.starts)),
            row("Minutes", f"{player.minutes:,}", lambda s: f"{s.minutes:,}"),
            row("Goals", str(player.goals), lambda s: str(s.goals)),
            row("Assists", str(player.assists), lambda s: str(s.assists)),
            *(
                [
                    row("Clean sheets", str(player.clean_sheets), lambda s: str(s.clean_sheets)),
                    row("Conceded", str(player.goals_conceded), lambda s: str(s.goals_conceded)),
                ]
                if keeper_or_defender
                else []
            ),
            *([row("Saves", str(player.saves), lambda s: str(s.saves))] if player.position == "GKP" else []),
            row("Bonus", str(player.bonus), lambda s: str(s.bonus)),
            row("xG", f"{player.expected_goals:.2f}", lambda s: f"{s.expected_goals:.2f}"),
            row("xA", f"{player.expected_assists:.2f}", lambda s: f"{s.expected_assists:.2f}"),
            # The market's own verdict on a season: what the price did over it.
            StatRow(
                label="Price",
                values=[as_millions(player.cost)]
                + [f"{as_millions(s.start_cost)} → {as_millions(s.end_cost)}" for s in seasons],
            ),
        ]
        return StatTable(title="By season", columns=columns, rows=rows)

    def _season_started(self) -> bool:
        """Whether this season has produced anything to report yet.

        A gameweek in progress is not a gameweek with totals in it — the
        catalog is still all noughts until one finishes.
        """
        try:
            return any(gw.finished for gw in self.client.get_gameweeks())
        except FPLAPIError as e:
            logger.warning(f"Assuming the season is under way: {e}")
            return True

    @staticmethod
    def _season_label(past: list[PastSeason]) -> str:
        """This season's name, which FPL only ever states about finished ones.

        Derived from the most recent finished season rather than from a clock:
        a football season spans two calendar years and the changeover is not on
        a date anybody could hardcode.
        """
        if not past:
            return "This season"
        try:
            start, end = past[0].season.split("/")
            return f"{int(start) + 1}/{int(end) + 1:02d}"
        except (ValueError, IndexError):
            return "This season"

    def _fixture_line(self, player: Player, gameweek: int) -> str:
        return self._fixtures_by_club([player], gameweek).get(player.team, "no fixture")

    @staticmethod
    def _set_pieces(player: Player) -> list[Stat]:
        """Whose duty it is, which is most of the gap between two similar prices.

        Only listed when they are on them: "not on penalties" for every player
        who is not would be nineteen rows of nothing.
        """
        duties = [
            ("Penalties", player.penalties_order),
            ("Corners", player.corners_order),
            ("Free kicks", player.freekicks_order),
        ]
        taken = [
            Stat(label=name, value=f"#{order}", tone="good" if order == 1 else "neutral")
            for name, order in duties
            if order is not None
        ]
        return taken or [Stat(label="Set pieces", value="none")]

    def roster(self, league_id: str) -> list[PlayerCard]:
        """The squad in full, with the season numbers a week view leaves out."""
        return self._squad_cards(self._resolve_entry_id())

    def teams(self, league_id: str) -> list[TeamRef]:
        """Everyone in the mini-league, yours first.

        The table is the membership list — FPL has no separate one — so a
        league whose table cannot be read has no teams to browse either.
        """
        entry_id = self._resolve_entry_id()
        league = self._find_league(league_id, entry_id)
        if league is None:
            return []
        try:
            table = self.client.get_standings(league.id, league.is_h2h)
        except FPLAPIError as e:
            logger.warning(f"Cannot list the league's teams: {e}")
            return []
        refs = [
            TeamRef(
                team_id=str(row.entry),
                name=row.entry_name,
                detail=row.manager,
                is_mine=row.entry == entry_id,
            )
            for row in table
        ]
        return sorted(refs, key=lambda ref: (not ref.is_mine, ref.name.lower()))

    def roster_of(self, league_id: str, team_id: str) -> list[PlayerCard]:
        """Another manager's squad, in the same columns as your own."""
        if not team_id.isdigit():
            raise TeamNotFoundError(team_id)
        return self._squad_cards(int(team_id))

    def free_agents(self, league_id: str) -> list[PlayerCard]:
        """The transfer market: everyone you do not already own.

        FPL has no waiver wire — every player is buyable at a price — so the
        question is not who is free but who is worth the money. Ranked on the
        game's own projection, which is what a transfer is decided on.
        """
        entry_id = self._resolve_entry_id()
        current = self.client.current_gameweek()
        gameweek = current.id if current else self._last_completed_gameweek(self.client.upcoming_gameweek().id)
        squad, _, _, _ = self._squad(entry_id, gameweek)
        owned = {pick.element for pick in squad.picks}

        market = [p for p in self.client.get_players().values() if p.id not in owned and p.is_available]
        market.sort(key=lambda p: (-p.expected_points, -p.form))
        return [self._market_card(p) for p in market[:MARKET_BROWSE_LIMIT]]

    def _squad_cards(self, entry_id: int) -> list[PlayerCard]:
        """One table shape for any manager's fifteen."""
        gameweek = self._last_completed_gameweek(self.client.upcoming_gameweek().id)
        squad, players, _, _ = self._squad(entry_id, gameweek)

        captain = next((p.element for p in squad.picks if p.is_captain), None)
        by_position = {p.element: p for p in squad.picks}
        cards = []
        for player in sorted(players, key=lambda p: by_position[p.id].position):
            pick = by_position[player.id]
            cards.append(
                PlayerCard(
                    player_id=str(player.id),
                    tone="warning" if player.availability else "neutral",
                    columns={
                        **self._market_columns(player),
                        "Slot": ("C" if player.id == captain else "XI") if pick.is_starting else "BN",
                    },
                )
            )
        return cards

    def _market_card(self, player: Player) -> PlayerCard:
        return PlayerCard(
            player_id=str(player.id),
            tone="warning" if player.availability else "neutral",
            columns=self._market_columns(player),
        )

    @staticmethod
    def _market_columns(player: Player) -> dict[str, str]:
        return {
            "Player": player.name,
            "Pos": player.position,
            "Club": player.team,
            "Price": as_millions(player.cost),
            "xPts": f"{player.expected_points:.1f}",
            "Form": f"{player.form:.1f}",
            "Points": str(player.total_points),
            "xGI": f"{player.expected_goal_involvements:.2f}",
            "Owned": f"{player.selected_by:.1f}%",
            "Status": player.availability,
        }

    def summary(self, league_id: str) -> Summary:
        """The gameweek as it stands: both squads, the fixtures, the swaps.

        Reaches for the squad, the history and the tie — everything the week is
        made of — and stops short of the transfer market, which is the expensive
        half of a report and answers a different question.
        """
        entry_id = self._resolve_entry_id()
        upcoming = self.client.upcoming_gameweek()
        # The gameweek being played, not the next deadline. Points are landing
        # in this one; the next one is a plan, and the report is where plans go.
        current = self.client.current_gameweek()
        week = current.id if current else self._last_completed_gameweek(upcoming.id)
        squad, players, starters, bench = self._squad(entry_id, week)

        captain_id = next((pick.element for pick in squad.picks if pick.is_captain), None)
        captain = next((p for p in starters if p.id == captain_id), None)
        best = best_lineup(players)
        entry = self.client.get_entry(entry_id)
        fixtures = self._fixtures_by_club(players, week)
        live = self._live_points(week)

        return Summary(
            headline=self._headline(
                entry,
                league_id,
                squad,
                # Keyed to the next deadline, because that is the one an
                # allowance can still be spent against.
                free_transfers(self.client.get_history(entry_id), upcoming.id),
                best,
                points_with_captain(starters, captain),
                upcoming,
            ),
            mine=Side(
                name=entry.name,
                detail=f"GW{week}",
                points=_total(starters, captain_id, live),
                lineup=[self._spot(p, fixtures, live, captain=p.id == captain_id) for p in starters],
                bench=[self._spot(p, fixtures, live) for p in bench],
            ),
            opponent=self._opponent(league_id, entry_id, week, fixtures, live),
            swaps=[
                Swap(
                    start=change.start.name,
                    out=change.drop.name if change.drop else "",
                    gain=f"+{change.gain:.1f} xPts",
                )
                for change in lineup_changes(starters, best)
            ],
            fixtures=self._warnings(players, fixtures),
            window=_window(current or upcoming, live=any(s.has_played for s in live.values())),
        )

    def _live_points(self, gameweek: int) -> dict[int, LiveStat]:
        """What the squad has actually scored, or nothing before a ball is kicked.

        Enrichment, not a dependency: a gameweek with no live feed yet is a
        gameweek shown on projections, which is what it was before this.
        """
        try:
            return self.client.get_live(gameweek)
        except FPLAPIError as e:
            logger.warning(f"Continuing without live points: {e}")
            return {}

    def schedule(self, league_id: str) -> LeagueSchedule:
        """The season, the table, and the real matches behind the gameweek.

        No activity section: FPL publishes no transfer feed for a mini-league,
        and a tab that is always empty is worse than one that is not there.
        """
        entry_id = self._resolve_entry_id()
        league = self._find_league(league_id, entry_id)
        upcoming = self.client.upcoming_gameweek()
        current = self.client.current_gameweek()
        # Marked on the week being played, so the season table and the week
        # view agree about which row is "now".
        playing = current.id if current else upcoming.id

        # The real matches stand on their own: they are the gameweek itself,
        # and they are the same whether or not this id names a real league.
        if league is None:
            return LeagueSchedule(matches=self._matches(playing))

        return LeagueSchedule(
            season=self._season_rows(league, entry_id, playing),
            standings=self._standings(league, entry_id),
            matches=self._matches(playing),
        )

    def _find_league(self, league_id: str, entry_id: int) -> MiniLeague | None:
        """The mini-league behind an id, or None when there is no such thing.

        `list_leagues` falls back to the manager's overall standing when they
        have joined no private league, and that id is the entry's own — a place
        in a table of eleven million, not a league with fixtures to read.
        """
        entry = self.client.get_entry(entry_id)
        return next((lg for lg in entry.leagues if str(lg.id) == league_id), None)

    def _season_rows(self, league: MiniLeague, entry_id: int, playing: int) -> list[ScheduleRow]:
        """Your gameweeks, with the tie in each where the league has one.

        A classic league has no season in this sense — it is a running table,
        not a set of fixtures — so it gets the gameweeks and their deadlines
        without opponents, which is still the calendar somebody came for.
        """
        gameweeks = self.client.get_gameweeks()
        ties = {}
        if league.is_h2h:
            try:
                ties = self.client.get_h2h_season(league.id, entry_id)
            except FPLAPIError as e:
                logger.warning(f"Continuing without the h2h season: {e}")

        rows = []
        for gw in gameweeks:
            tie = ties.get(gw.id)
            played = gw.id < playing
            rows.append(
                ScheduleRow(
                    label=gw.name,
                    date=_deadline_label(gw.deadline),
                    opponent=tie.opponent_name if tie else "",
                    detail="" if tie else ("no tie" if league.is_h2h else ""),
                    result=f"{tie.my_points}-{tie.opponent_points}" if tie and played else "",
                    tone=self._tie_tone(tie, played),
                    is_current=gw.id == playing,
                )
            )
        return rows

    @staticmethod
    def _tie_tone(tie: H2HMatch | None, played: bool) -> Tone:
        if not tie or not played:
            return "neutral"
        if tie.my_points == tie.opponent_points:
            return "neutral"
        return "good" if tie.my_points > tie.opponent_points else "warning"

    def _standings(self, league: MiniLeague, entry_id: int) -> list[StandingRow]:
        try:
            table = self.client.get_standings(league.id, league.is_h2h)
        except FPLAPIError as e:
            logger.warning(f"Continuing without the table: {e}")
            return []
        return [
            StandingRow(
                rank=row.rank,
                name=row.entry_name,
                detail=row.manager,
                record=row.record,
                # In h2h the table is on league points and the FPL total is the
                # tiebreak; in a classic league they are the same number.
                points=f"{row.total:,}" if not league.is_h2h else f"{row.total} ({row.points_for:,} pts)",
                team_id=str(row.entry),
                is_mine=row.entry == entry_id,
            )
            for row in table
        ]

    def _matches(self, gameweek: int) -> list[Match]:
        """The real matches the gameweek is made of, with both difficulties.

        Difficulty is per side, so it is carried per side: a fixture is easy
        for one of these clubs and hard for the other, and one number for the
        match would be true of neither.
        """
        try:
            fixtures = self.client.get_fixtures(gameweek)
        except FPLAPIError as e:
            logger.warning(f"Continuing without fixtures: {e}")
            return []
        return [
            Match(
                label=_kickoff_label(f.kickoff),
                home=f.home,
                away=f.away,
                detail=f"FDR {f.home_difficulty} / {f.away_difficulty}",
                tone="warning" if max(f.home_difficulty, f.away_difficulty) >= HARD_FIXTURE else "neutral",
            )
            for f in sorted(fixtures, key=lambda f: (f.kickoff is None, f.kickoff))
        ]

    def _opponent(
        self,
        league_id: str,
        entry_id: int,
        gameweek: int,
        fixtures: dict[str, str],
        live: dict[int, LiveStat],
    ) -> Side | None:
        """Who this entry is playing, and what they are fielding.

        Only head-to-head leagues pair managers; a classic league is a table,
        so there is no opponent to show and saying so beats inventing one.
        """
        league = self._find_league(league_id, entry_id)
        if league is None or not league.is_h2h:
            return None

        try:
            match = self.client.get_h2h_match(league.id, entry_id, gameweek)
            if match is None:
                return None
            squad, players, starters, bench = self._squad(match.opponent_entry, gameweek)
        except FPLAPIError as e:
            # The rest of the page is about your own squad and still stands.
            logger.warning(f"Skipping the head-to-head opponent: {e}")
            return None

        their_fixtures = self._fixtures_by_club(players, gameweek)
        their_captain = next((pick.element for pick in squad.picks if pick.is_captain), None)
        return Side(
            name=match.opponent_name,
            detail=f"GW{gameweek}",
            # The game's own total rather than a sum of the rows: it already
            # accounts for auto-subs, which a squad list cannot show.
            points=f"{match.opponent_points} pts",
            lineup=[self._spot(p, their_fixtures, live, captain=p.id == their_captain) for p in starters],
            bench=[self._spot(p, their_fixtures, live) for p in bench],
        )

    def _spot(
        self,
        player: Player,
        fixtures: dict[str, str],
        live: dict[int, LiveStat],
        captain: bool = False,
    ) -> Spot:
        """One row of a lineup, showing what happened where anything has.

        Once a gameweek is under way the scored total is the number somebody is
        looking for, and a projection beside it is last week's guess about a
        question already being answered. Before then, the projection is all
        there is.
        """
        flag = player.availability
        stat = live.get(player.id)
        played = stat is not None and stat.has_played
        points = (stat.points * 2 if captain else stat.points) if stat and played else None
        return Spot(
            player_id=str(player.id),
            player=player.name + (" (C)" if captain else ""),
            detail=f"{player.position} · {player.team} {fixtures.get(player.team, 'no fixture')}"
            + (f" · {flag}" if flag else ""),
            # Points once they exist, the projection until then. A player whose
            # match is on Sunday has not blanked, and showing them a nought
            # says they have.
            value=f"{points} pts" if points is not None else f"{effective_points(player):.1f} xPts",
            tone=self._spot_tone(player, fixtures, points, flag),
        )

    @staticmethod
    def _spot_tone(player: Player, fixtures: dict[str, str], points: int | None, flag: str) -> Tone:
        """A haul is worth seeing, and so is a blank.

        Once somebody has played, the points are what the row is about: a doubt
        about a player who got through ninety minutes is no longer a doubt.
        Until then the availability flag is the whole signal.
        """
        if points is None:
            return "warning" if flag or player.team not in fixtures else "neutral"
        if points >= HAUL:
            return "good"
        return "warning" if points <= BLANK else "neutral"

    @staticmethod
    def _warnings(players: list[Player], fixtures: dict[str, str]) -> list[Stat]:
        """Only what is worth watching, not every fixture.

        Each player row already carries its own opponent and difficulty, so a
        full list of clubs repeats the page back at itself. A blank gameweek
        and a double are the two cases that change what a squad is worth.
        """
        notable = []
        for club in sorted({p.team for p in players}):
            fixture = fixtures.get(club)
            if fixture is None:
                notable.append(Stat(label=club, value="no fixture — these players score nothing", tone="warning"))
            elif "," in fixture:
                notable.append(Stat(label=club, value=f"double gameweek — {fixture}", tone="good"))
        return notable

    def _fixtures_by_club(self, players: list[Player], gameweek: int) -> dict[str, str]:
        """Each owned club's opponent this gameweek; absent means a blank."""
        try:
            fixtures = self.client.get_fixtures(gameweek)
        except FPLAPIError as e:
            logger.warning(f"Skipping FPL fixtures: {e}")
            return {}
        by_club: dict[str, str] = {}
        for club in {p.team for p in players}:
            matches = [m for f in fixtures if (m := f.opponent_of(club))]
            if matches:
                by_club[club] = ", ".join(
                    f"{'vs' if home else 'at'} {opponent} ({difficulty})" for opponent, difficulty, home in matches
                )
        return by_club

    # ── context ─────────────────────────────────────────────────────

    def build_context(self, league_id: str) -> SportContext:
        entry_id = self._resolve_entry_id()
        upcoming = self.client.upcoming_gameweek()
        last = self._last_completed_gameweek(upcoming.id)

        entry = self.client.get_entry(entry_id)
        squad, players, current_starters, current_bench = self._squad(entry_id, last)
        catalog = self.client.get_players()

        captain_id = next((pick.element for pick in squad.picks if pick.is_captain), None)
        captain = next((p for p in current_starters if p.id == captain_id), None)
        best = best_lineup(players)
        current_points = points_with_captain(current_starters, captain)
        changes = lineup_changes(current_starters, best)
        allowance = free_transfers(self.client.get_history(entry_id), upcoming.id)

        market = sorted(
            (p for p in catalog.values() if p.is_available and p.minutes > 0),
            key=effective_points,
            reverse=True,
        )
        owned = {p.id for p in players}
        market_lines = {p.name: self._market_line(p) for p in market if p.id not in owned}
        market_lines = dict(list(market_lines.items())[:MARKET_LIMIT])

        transfers = affordable_transfers(players, market, squad.bank, limit=TRANSFER_LIMIT)

        situation = self._situation(entry, league_id, squad, upcoming.name, upcoming.average_score)
        constraints = self._constraints(squad, allowance, best, current_points)

        return SportContext(
            headline=self._headline(entry, league_id, squad, allowance, best, current_points, upcoming),
            prompt=FPL_SCOUT_PROMPT.format(
                situation=situation,
                constraints=constraints,
                lineup_str="".join(self._squad_line(p, captain=p.id == captain_id) for p in current_starters)
                or "- (no eleven set)\n",
                bench_str="".join(self._squad_line(p) for p in current_bench) or "- (none)\n",
                changes_str=self._changes_lines(changes),
                fixtures_str=self._fixture_lines(players, upcoming.id),
                transfers_str=self._transfer_lines(transfers),
                market_str="".join(market_lines.values()) or "- (none)\n",
                free_transfers=allowance,
            ),
            situation=situation,
            constraints=constraints,
            extra=f"LINEUP CHANGES IMPLIED BY EXPECTED POINTS:\n{self._changes_lines(changes)}",
            roster_lines={p.name: self._squad_line(p) for p in players},
            candidate_lines=market_lines,
        )

    @staticmethod
    def _headline(
        entry: Entry,
        league_id: str,
        squad: Squad,
        allowance: int,
        best: Lineup,
        current_points: float,
        upcoming: Gameweek,
    ) -> list[Stat]:
        """Where this squad stands, in FPL's own currency.

        Points left on the bench is the only figure here that is a mistake
        rather than a fact, so it is the only one that ever warns — and only
        when the current eleven really is behind the best legal one.
        """
        behind = round(best.points - current_points, 1)
        league = next((lg for lg in entry.leagues if str(lg.id) == league_id), None)

        stats = [
            Stat(label="Gameweek", value=str(upcoming.id)),
            # Shown in UTC, which is what the API states. A local rendering would
            # be friendlier and would also be a guess about where this is read.
            Stat(label="Deadline", value=f"{upcoming.deadline:%a %d %b %H:%M} UTC"),
            Stat(label="Points", value=f"{entry.overall_points:,}"),
            Stat(label="Overall", value=f"{entry.overall_rank:,}"),
        ]
        if league:
            stats.append(Stat(label="Mini-league", value=league.standing))
        stats += [
            Stat(label="Bank", value=as_millions(squad.bank)),
            Stat(label="Free transfers", value=str(allowance), tone="good" if allowance else "neutral"),
        ]
        if behind > 0:
            stats.append(Stat(label="On bench", value=f"+{behind:.1f} xPts", tone="warning"))
        return stats

    # ── prompt blocks ───────────────────────────────────────────────

    def _situation(self, entry: Entry, league_id: str, squad: Squad, gameweek_name: str, average: int) -> str:
        """Rank, mini-league standing and money, as the prompt's opening block."""
        lines = [
            f"TEAM: {entry.name} ({entry.manager})",
            f"GAMEWEEK: {gameweek_name}" + (f", average score last time {average}" if average else ""),
            f"OVERALL: {entry.overall_points} points, rank {entry.overall_rank:,}",
        ]
        league = next((lg for lg in entry.leagues if str(lg.id) == league_id), None)
        if league:
            lines.append(f"MINI-LEAGUE: {league.name} — {league.standing}")
        lines.append(f"MONEY: {as_millions(squad.bank)} in the bank, squad worth {as_millions(squad.value)}")
        if squad.points_on_bench:
            lines.append(f"LAST GAMEWEEK: {squad.points_on_bench} points were left on the bench.")
        return "\n".join(lines) + "\n"

    def _constraints(self, squad: Squad, allowance: int, best: Lineup, current_points: float) -> str:
        """What the manager can actually do this week, and what it is worth."""
        current = round(current_points, 1)
        gain = round(best.points - current, 1)
        lines = [
            f"FREE TRANSFERS: {allowance}. Each extra transfer costs {TRANSFER_HIT} points.",
            f"BANK: {as_millions(squad.bank)}.",
            f"- The eleven as set expects {current:.1f} points with its captain doubled.",
            f"- The best legal eleven is a {best.formation} expecting {best.points:.1f} with the captain doubled"
            + (f", {gain:.1f} more than the current shape.\n" if gain > 0 else ".\n"),
            "- A start/sit change is free. A transfer is not, so it has to beat the alternative by "
            "enough to be worth the allowance.",
        ]
        if squad.active_chip:
            lines.insert(0, f"CHIP PLAYED LAST GAMEWEEK: {squad.active_chip}.")
        return "\n".join(lines)

    @staticmethod
    def _squad_line(player: Player, captain: bool = False) -> str:
        flag = player.availability
        note = f" [{flag}]" if flag else ""
        mark = " (C)" if captain else ""
        return (
            f"- {player.name}{mark} ({player.position}, {player.team}, {as_millions(player.cost)})"
            f"{note}: {player.expected_points:.1f} xPts, form {player.form:.1f}, "
            f"{player.total_points} pts this season\n"
        )

    @staticmethod
    def _market_line(player: Player) -> str:
        return (
            f"- {player.name} ({player.position}, {player.team}, {as_millions(player.cost)}): "
            f"{player.expected_points:.1f} xPts, form {player.form:.1f}, "
            f"{player.expected_goal_involvements:.2f} xGI, owned by {player.selected_by:.1f}%\n"
        )

    @staticmethod
    def _changes_lines(changes: list[LineupChange]) -> str:
        if not changes:
            return "- None; the eleven as set is already the best legal shape.\n"
        return "".join(
            f"- START {c.start.name} ({c.start.position}) for "
            f"{c.drop.name if c.drop else 'an empty place'}: +{c.gain:.1f} xPts\n"
            for c in changes
        )

    @staticmethod
    def _transfer_lines(transfers: list[Transfer]) -> str:
        if not transfers:
            return "- (nothing in the bank buys an upgrade)\n"
        return "".join(
            f"- {t.incoming.name} ({t.incoming.position}, {t.incoming.team}, {as_millions(t.incoming.cost)}) "
            f"for {t.out.name} ({as_millions(t.out.cost)}): +{t.gain:.1f} xPts, "
            f"{'costs' if t.cost > 0 else 'frees'} {as_millions(abs(t.cost))}\n"
            for t in transfers
        )

    def _fixture_lines(self, players: list[Player], gameweek: int) -> str:
        """Each owned club's next match and how hard the game rates it.

        A club with no fixture is a blank gameweek — every player of theirs
        scores nothing — which is the single most important thing the report can
        be told, so it is stated rather than omitted.
        """
        try:
            fixtures = self.client.get_fixtures(gameweek)
        except FPLAPIError as e:
            # Difficulty is context, not the basis of the report; losing it
            # should shrink the prompt rather than fail the run.
            logger.warning(f"Skipping FPL fixtures: {e}")
            return "- (unavailable)\n"

        clubs = sorted({p.team for p in players})
        lines = []
        for club in clubs:
            matches = [m for f in fixtures if (m := f.opponent_of(club))]
            if not matches:
                lines.append(f"- {club}: no fixture — blank gameweek, every {club} player scores 0.\n")
                continue
            rendered = ", ".join(
                f"{'vs' if home else 'at'} {opponent} (difficulty {difficulty})"
                for opponent, difficulty, home in matches
            )
            note = " — double gameweek" if len(matches) > 1 else ""
            lines.append(f"- {club}: {rendered}{note}\n")
        return "".join(lines) or "- (none)\n"


def _window(gameweek: Gameweek, live: bool = False) -> str:
    """Which gameweek, and either when it locks or that it already has.

    A deadline is the useful date right up until it passes; after that the
    useful fact is that points are landing.
    """
    if live:
        return f"{gameweek.name} · in progress"
    label = _deadline_label(gameweek.deadline)
    return f"{gameweek.name} · deadline {label}" if label else gameweek.name


def _total(starters: list[Player], captain_id: int | None, live: dict[int, LiveStat]) -> str:
    """The eleven's live score, doubling the captain.

    Empty until somebody has actually played rather than zero, which reads as a
    bad week instead of a week that has not started.
    """
    if not any(live.get(p.id) and live[p.id].has_played for p in starters):
        return ""
    scored = sum(live[p.id].points * (2 if p.id == captain_id else 1) for p in starters if p.id in live)
    return f"{scored} pts"


def _deadline_label(deadline: datetime | None) -> str:
    """A gameweek is bounded by its deadline, not by a kickoff.

    Rendered in UTC, which is what FPL publishes and what its own site shows
    every manager regardless of where they are.
    """
    return at_time(deadline) if deadline else ""


def _kickoff_label(kickoff: datetime | None) -> str:
    return at_time(kickoff) if kickoff else "TBC"
