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

from the_front_office.adapters.outbound.platforms.fpl.client import FPLClient, free_transfers
from the_front_office.adapters.outbound.platforms.fpl.types import (
    TRANSFER_HIT,
    Entry,
    Gameweek,
    Player,
    Squad,
    as_millions,
)
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
from the_front_office.domain.errors import FPLAPIError, LeagueNotFoundError
from the_front_office.domain.models import SportContext, Stat
from the_front_office.domain.ports import LeagueRef

logger = logging.getLogger(__name__)

MARKET_LIMIT = 20
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
                detail=f"{lg.rank:,} of {lg.rank_count:,} · {entry.name}",
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

    def roster_rows(self, league_id: str) -> list[dict[str, str]]:
        """The squad as table rows, without pulling the market or the fixtures."""
        entry_id = self._resolve_entry_id()
        gameweek = self._last_completed_gameweek(self.client.upcoming_gameweek().id)
        squad, players, _, _ = self._squad(entry_id, gameweek)

        captain = next((p.element for p in squad.picks if p.is_captain), None)
        by_position = {p.element: p for p in squad.picks}
        rows = []
        for player in sorted(players, key=lambda p: by_position[p.id].position):
            pick = by_position[player.id]
            rows.append(
                {
                    "Player": player.name,
                    "Pos": player.position,
                    "Club": player.team,
                    "Price": as_millions(player.cost),
                    "Slot": ("C" if player.id == captain else "XI") if pick.is_starting else "BN",
                    "xPts": f"{player.expected_points:.1f}",
                    "Status": player.availability,
                }
            )
        return rows

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
            stats.append(Stat(label="Mini-league", value=f"{league.rank:,} of {league.rank_count:,}"))
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
            lines.append(f"MINI-LEAGUE: {league.name} — {league.rank:,} of {league.rank_count:,}")
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
