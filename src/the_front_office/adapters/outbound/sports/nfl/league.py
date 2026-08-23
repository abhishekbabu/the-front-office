"""The league beyond this week: the season, the table, the real games, the moves.

Separate from the week because it answers a different question asked at a
different time — how the season is going, rather than what to do about Sunday —
and it costs requests the week does not need. Nobody checking a lineup should
wait on eighteen weeks of matchups.
"""

import logging
from typing import Any

from the_front_office.adapters.outbound.platforms.sleeper.client import SleeperClient
from the_front_office.adapters.outbound.platforms.sleeper.types import SleeperRoster, Transaction
from the_front_office.adapters.outbound.sports.nfl.week import Week, day, games_by_week, moment, week_dates
from the_front_office.domain.errors import SleeperAPIError
from the_front_office.domain.models import ActivityRow, LeagueSchedule, Match, ScheduleRow, StandingRow, Tone

logger = logging.getLogger(__name__)

REGULAR_SEASON_WEEKS = 18

# "What did I miss", not the season's whole transaction log.
ACTIVITY_WEEKS = 3

TRANSACTION_LABELS = {
    "waiver": "Waiver",
    "free_agent": "Free agent",
    "trade": "Trade",
    "commissioner": "Commissioner",
}


def build(client: SleeperClient, state: Week, league_id: str) -> LeagueSchedule:
    """The season, the table, this week's real games, and what the league did."""
    rosters = client.get_rosters(league_id)
    names = client.get_league_users(league_id)
    by_roster = {r.roster_id: r for r in rosters}

    return LeagueSchedule(
        season=_season_rows(client, state, league_id, by_roster, names),
        standings=_standings(state, rosters, names),
        matches=_matches(client, state),
        activity=_activity(client, state, league_id, by_roster, names),
    )


def _season_rows(
    client: SleeperClient,
    state: Week,
    league_id: str,
    by_roster: dict[int, SleeperRoster],
    names: dict[str, str],
) -> list[ScheduleRow]:
    """Your own season, week by week, with who you play and how it went.

    Eighteen matchup fetches, run concurrently and cached — asked one at a
    time they are the whole wait on the page.
    """
    games = games_by_week(client, state.season)
    weeks = list(range(1, REGULAR_SEASON_WEEKS + 1))
    try:
        by_week = client.get_matchups_bulk(league_id, weeks)
    except SleeperAPIError as e:
        logger.warning(f"Continuing without the season's matchups: {e}")
        by_week = {}

    rows: list[ScheduleRow] = []
    for week in weeks:
        matchups = by_week.get(week, [])
        mine = next((m for m in matchups if m.get("roster_id") == state.roster.roster_id), None)
        theirs = _other_side(matchups, mine, state.roster.roster_id)
        opponent = by_roster.get(int(theirs.get("roster_id", 0))) if theirs else None

        rows.append(
            ScheduleRow(
                label=f"Week {week}",
                date=week_dates(games.get(week, [])),
                opponent=names.get(opponent.owner_id, "") if opponent else "",
                detail=opponent.record if opponent else "bye",
                result=_result(mine, theirs, week, state.week),
                tone=_week_tone(mine, theirs, week, state.week),
                is_current=week == state.week,
            )
        )
    return rows


def _other_side(matchups: list[dict[str, Any]], mine: dict[str, Any] | None, roster_id: int) -> Any:
    if not mine or mine.get("matchup_id") is None:
        return None
    return next(
        (m for m in matchups if m.get("matchup_id") == mine.get("matchup_id") and m.get("roster_id") != roster_id),
        None,
    )


def _result(mine: Any, theirs: Any, week: int, current: int) -> str:
    """The score, and only once there is one. A future week is not 0-0."""
    if week >= current or not mine or not theirs:
        return ""
    return f"{float(mine.get('points') or 0):.1f}-{float(theirs.get('points') or 0):.1f}"


def _week_tone(mine: Any, theirs: Any, week: int, current: int) -> Tone:
    if week >= current or not mine or not theirs:
        return "neutral"
    return "good" if float(mine.get("points") or 0) > float(theirs.get("points") or 0) else "warning"


def _standings(state: Week, rosters: list[SleeperRoster], names: dict[str, str]) -> list[StandingRow]:
    """The table, sorted the way the league is: record first, then points."""
    ordered = sorted(rosters, key=lambda r: (-(r.wins), -(r.points_for)))
    return [
        StandingRow(
            rank=i,
            name=names.get(r.owner_id, f"Roster {r.roster_id}"),
            record=r.record,
            points=f"{r.points_for:.1f}",
            team_id=str(r.roster_id),
            is_mine=r.roster_id == state.roster.roster_id,
        )
        for i, r in enumerate(ordered, start=1)
    ]


def _matches(client: SleeperClient, state: Week) -> list[Match]:
    """The real games this fantasy week is made of.

    The whole slate rather than only the clubs you hold: which of them matters
    changes with every waiver, and it is one cached request either way.
    """
    games = games_by_week(client, state.season).get(state.week, [])
    mine = {p.team for p in state.projected}
    return [
        Match(
            label=day(game.date),
            home=game.home,
            away=game.away,
            # Whether you have anyone in it, which is the only thing that makes
            # one game on a Sunday slate different from another.
            detail="you have players" if {game.home, game.away} & mine else "",
            tone="good" if {game.home, game.away} & mine else "neutral",
        )
        for game in games
    ]


def _activity(
    client: SleeperClient,
    state: Week,
    league_id: str,
    by_roster: dict[int, SleeperRoster],
    names: dict[str, str],
) -> list[ActivityRow]:
    """What the league has done lately, newest first.

    Bounded to the last few weeks rather than the season: this is "what did I
    miss", and a hundred rows of September waivers is not that.
    """
    dated: list[tuple[int, ActivityRow]] = []
    for week in range(max(1, state.week - ACTIVITY_WEEKS + 1), state.week + 1):
        try:
            transactions = client.get_transactions(league_id, week)
        except SleeperAPIError as e:
            logger.warning(f"Skipping week {week} activity: {e}")
            continue
        dated.extend(_activity_rows(transactions, state, by_roster, names))
    # Sorted on the instant, not on the string that renders it: "Sep 3" sorts
    # before "Sep 21" alphabetically and after it in time.
    return [row for _, row in sorted(dated, key=lambda pair: pair[0], reverse=True)]


def _activity_rows(
    transactions: list[Transaction],
    state: Week,
    by_roster: dict[int, SleeperRoster],
    names: dict[str, str],
) -> list[tuple[int, ActivityRow]]:
    rows: list[tuple[int, ActivityRow]] = []
    for t in transactions:
        roster = by_roster.get(t.roster_ids[0]) if t.roster_ids else None
        moved = [f"+{_name_of(pid, state)}" for pid in t.adds] + [f"-{_name_of(pid, state)}" for pid in t.drops]
        rows.append(
            (
                t.when,
                ActivityRow(
                    when=moment(t.when),
                    who=names.get(roster.owner_id, "") if roster else "",
                    what=TRANSACTION_LABELS.get(t.kind, t.kind),
                    detail=", ".join(moved),
                    tone="good" if roster and roster.roster_id == state.roster.roster_id else "neutral",
                ),
            )
        )
    return rows


def _name_of(player_id: str, state: Week) -> str:
    meta = state.players.get(player_id)
    return str(meta.get("name") or player_id) if meta else player_id
