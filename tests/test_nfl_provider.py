"""Tests for the Sleeper football provider."""

from typing import Any

import pytest

from the_front_office.adapters.outbound.platforms.sleeper.types import (
    PlayerMeta,
    ScheduledGame,
    SeasonState,
    SeasonStats,
    SleeperLeague,
    SleeperRoster,
    SleeperUser,
    Transaction,
    TrendingPlayer,
    WeeklyProjection,
)
from the_front_office.adapters.outbound.sports.nfl.sleeper import SleeperNFLProvider
from the_front_office.domain.errors import LeagueNotFoundError, PlayerNotFoundError, SleeperAPIError, TeamNotFoundError

MY_ID = "user-1"


def _proj(pid: str, name: str, pos: str, pts: float, team: str = "BUF", opp: str = "MIA") -> WeeklyProjection:
    return WeeklyProjection(player_id=pid, name=name, position=pos, team=team, opponent=opp, points=pts)


class FakeSleeper:
    """Stands in for SleeperClient."""

    def __init__(
        self,
        rosters: list[SleeperRoster] | None = None,
        projections: dict[str, WeeklyProjection] | None = None,
        league: SleeperLeague | None = None,
        matchups: list[dict[str, Any]] | None = None,
        trending: list[TrendingPlayer] | None = None,
        trending_error: Exception | None = None,
        season_stats: dict[str, dict[str, SeasonStats]] | None = None,
        season_stats_error: Exception | None = None,
        season_schedule: list[ScheduledGame] | None = None,
        schedule_error: Exception | None = None,
        transactions: dict[int, list[Transaction]] | None = None,
        transactions_error: Exception | None = None,
    ) -> None:
        self.season_stats = season_stats if season_stats is not None else {}
        self.season_stats_error = season_stats_error
        self.season_schedule = season_schedule if season_schedule is not None else []
        self.matchups_error: Exception | None = None
        self.players_catalog: dict[str, PlayerMeta] | None = None
        self.schedule_error = schedule_error
        self.transactions = transactions if transactions is not None else {}
        self.transactions_error = transactions_error
        self.league = league or SleeperLeague(
            league_id="L1",
            name="Sunday Money",
            season="2026",
            total_rosters=12,
            scoring_format="pts_ppr",
            roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN"],
        )
        self.rosters = (
            rosters
            if rosters is not None
            else [
                SleeperRoster(
                    roster_id=1,
                    owner_id=MY_ID,
                    player_ids=["qb1", "rb1", "rb2"],
                    starter_ids=["qb1", "rb2"],
                    wins=2,
                    losses=1,
                    points_for=250.5,
                )
            ]
        )
        self.projections = projections or {}
        self.matchups = matchups or []
        self.trending = trending or []
        self.trending_error = trending_error
        self.matchup_fetches = 0

    def get_matchups_bulk(self, league_id: str, weeks: list[int]) -> dict[int, list[dict[str, Any]]]:
        return {w: self.get_matchups(league_id, w) for w in weeks}

    def get_season_schedule(self, season: str, sport: str = "nfl") -> list[ScheduledGame]:
        if self.schedule_error:
            raise self.schedule_error
        return self.season_schedule

    def get_transactions(self, league_id: str, week: int) -> list[Transaction]:
        if self.transactions_error:
            raise self.transactions_error
        return self.transactions.get(week, [])

    def get_season_stats(self, season: str, sport: str = "nfl") -> dict[str, SeasonStats]:
        if self.season_stats_error:
            raise self.season_stats_error
        return self.season_stats.get(season, {})

    def get_state(self, sport: str = "nfl") -> SeasonState:
        return SeasonState(week=3, season="2026", season_type="regular")

    def get_nfl_state(self) -> SeasonState:
        return self.get_state()

    def get_user(self, username: str) -> SleeperUser:
        return SleeperUser(user_id=MY_ID, username=username, display_name=username)

    def get_leagues(self, user_id: str, season: str) -> list[SleeperLeague]:
        return [self.league]

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        return self.rosters

    def get_league_users(self, league_id: str) -> dict[str, str]:
        return {MY_ID: "Me", "user-2": "Rival"}

    def get_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        self.matchup_fetches += 1
        if self.matchups_error:
            raise self.matchups_error
        return self.matchups

    def get_players(self) -> dict[str, PlayerMeta]:
        if self.players_catalog is not None:
            return self.players_catalog
        return {
            "qb1": PlayerMeta(player_id="qb1", name="Star QB", position="QB", team="BUF"),
            "rb1": PlayerMeta(player_id="rb1", name="Good RB", position="RB", team="BUF"),
            "rb2": PlayerMeta(player_id="rb2", name="Bad RB", position="RB", team="BUF"),
            "wr9": PlayerMeta(player_id="wr9", name="Waiver WR", position="WR", team="NYJ"),
            "bye1": PlayerMeta(player_id="bye1", name="Bye Guy", position="TE", team="LAR"),
        }

    def get_projections(self, season: str, week: int, scoring: str) -> dict[str, WeeklyProjection]:
        return self.projections

    def get_trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list[TrendingPlayer]:
        if self.trending_error:
            raise self.trending_error
        return self.trending


def _provider(client: FakeSleeper) -> SleeperNFLProvider:
    return SleeperNFLProvider(username="me", client=client)  # type: ignore[arg-type]


DEFAULT_PROJECTIONS = {
    "qb1": _proj("qb1", "Star QB", "QB", 22.0),
    "rb1": _proj("rb1", "Good RB", "RB", 18.0),
    "rb2": _proj("rb2", "Bad RB", "RB", 4.0),
    "wr9": _proj("wr9", "Waiver WR", "WR", 14.0, team="NYJ"),
}


# ── leagues ─────────────────────────────────────────────────────────────


def test_leagues_are_listed_with_format_and_size() -> None:
    refs = _provider(FakeSleeper()).list_leagues()
    assert len(refs) == 1
    assert refs[0].name == "Sunday Money"
    assert refs[0].sport == "nfl"
    assert "12-team" in refs[0].detail
    assert "PPR" in refs[0].detail


def test_missing_username_is_a_clear_error() -> None:
    provider = SleeperNFLProvider(username=None, client=FakeSleeper())  # type: ignore[arg-type]
    with pytest.raises(LeagueNotFoundError, match="SLEEPER_USERNAME"):
        provider.list_leagues()


def test_a_league_you_are_not_in_raises() -> None:
    with pytest.raises(LeagueNotFoundError, match="not one of yours"):
        _provider(FakeSleeper()).build_context("nope")


def test_owning_no_roster_raises() -> None:
    client = FakeSleeper(rosters=[SleeperRoster(roster_id=9, owner_id="someone-else", player_ids=[], starter_ids=[])])
    with pytest.raises(LeagueNotFoundError, match="do not own a roster"):
        _provider(client).build_context("L1")


# ── context ─────────────────────────────────────────────────────────────


def _context(**kwargs: Any) -> Any:
    client = FakeSleeper(projections=dict(DEFAULT_PROJECTIONS), **kwargs)
    return _provider(client).build_context("L1")


def test_prompt_names_the_scoring_format() -> None:
    """Every projection is in that currency; getting it wrong ranks by the wrong number."""
    assert "Full PPR" in _context().prompt


def test_roster_and_available_players_are_separated() -> None:
    ctx = _context()
    assert "Star QB" in ctx.roster_lines
    assert "Waiver WR" in ctx.candidate_lines
    assert "Waiver WR" not in ctx.roster_lines


def test_rostered_players_are_never_offered_as_waiver_adds() -> None:
    ctx = _context()
    assert "Good RB" not in ctx.candidate_lines


SMALL_LEAGUE = SleeperLeague(
    league_id="L1",
    name="Sunday Money",
    season="2026",
    total_rosters=12,
    scoring_format="pts_ppr",
    roster_positions=["QB", "RB", "BN", "BN"],
)


def test_implied_lineup_change_is_computed_and_shown() -> None:
    """One RB slot, and the worse RB is starting — the report must say so."""
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
    )
    prompt = _provider(client).build_context("L1").prompt
    assert "START Good RB" in prompt
    assert "for Bad RB" in prompt
    assert "+14.0 projected" in prompt


def test_an_optimal_lineup_is_reported_as_such() -> None:
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb1"])
        ],
    )
    assert "already the highest-projecting" in _provider(client).build_context("L1").prompt


def test_an_unfilled_slot_is_shown_as_empty() -> None:
    """A thin roster must read as a hole in the lineup, not silently shrink it."""
    assert "(empty)" in _context().prompt


def test_a_player_with_no_projection_is_kept_at_zero() -> None:
    """A bye or an inactive is a zero, and the report must see it — not silently
    drop the player from the roster."""
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "bye1"], starter_ids=["qb1"])],
    )
    ctx = _provider(client).build_context("L1")
    assert "Bye Guy" in ctx.roster_lines
    assert "0.0 proj pts" in ctx.roster_lines["Bye Guy"]
    assert "(no game)" in ctx.roster_lines["Bye Guy"]


def test_matchup_opponent_and_live_score_are_surfaced() -> None:
    ctx = _context(
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 60.2},
            {"roster_id": 2, "matchup_id": 7, "points": 71.8},
        ],
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]),
            SleeperRoster(roster_id=2, owner_id="user-2", player_ids=[], starter_ids=[], wins=3, losses=0),
        ],
    )
    assert "Rival" in ctx.situation
    assert "60.2" in ctx.situation
    assert "71.8" in ctx.situation


def test_a_week_with_no_matchup_says_so() -> None:
    assert "No head-to-head matchup" in _context(matchups=[{"roster_id": 1, "matchup_id": None}]).situation


def test_trending_players_are_included_with_their_projection() -> None:
    ctx = _context(trending=[TrendingPlayer(player_id="wr9", count=41234)])
    assert "Waiver WR" in ctx.prompt
    assert "41,234" in ctx.prompt


def test_trending_failure_degrades_without_losing_the_report() -> None:
    """An independent signal, not load-bearing."""
    ctx = _context(trending_error=SleeperAPIError("429"))
    assert "(unavailable)" in ctx.prompt
    assert ctx.roster_lines  # the rest still built


def test_constraints_compare_current_and_best_lineups() -> None:
    """The gap is the point: how many points are sitting on the bench."""
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
    )
    constraints = _provider(client).build_context("L1").constraints
    assert "LINEUP SLOTS" in constraints
    assert "Current lineup projects 26.0" in constraints  # 22 + 4
    assert "best legal lineup projects 40.0" in constraints  # 22 + 18
    assert "14.0 points are sitting on the bench" in constraints


def test_no_bench_gap_is_reported_when_already_optimal() -> None:
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb1"])
        ],
    )
    assert "sitting on the bench" not in _provider(client).build_context("L1").constraints


def test_a_player_is_never_both_starting_and_benched() -> None:
    """The lineup block shows what is set; the bench holds everyone else."""
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
    )
    prompt = _provider(client).build_context("L1").prompt
    lineup_block = prompt.split("YOUR CURRENT LINEUP")[1].split("BENCH:")[0]
    bench_block = prompt.split("BENCH:")[1].split("LINEUP CHANGES")[0]
    starting = {line.split(": ")[1].split(" (")[0] for line in lineup_block.strip().splitlines() if ": " in line}
    benched = {line.split("- ")[1].split(" (")[0] for line in bench_block.strip().splitlines() if line.startswith("- ")}
    assert not (starting & benched), f"{starting & benched} both starting and benched"


def test_the_bench_gap_matches_the_printed_figures() -> None:
    """The three numbers in the prompt must agree once rounded."""
    import re

    projections = {
        "qb1": _proj("qb1", "Star QB", "QB", 22.04),
        "rb1": _proj("rb1", "Good RB", "RB", 18.06),
        "rb2": _proj("rb2", "Bad RB", "RB", 4.04),
    }
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=projections,
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
    )
    constraints = _provider(client).build_context("L1").constraints
    current, best = (float(x) for x in re.findall(r"projects (\d+\.\d)", constraints))
    gap_match = re.search(r"so (\d+\.\d) points are sitting", constraints)
    assert gap_match is not None
    assert float(gap_match.group(1)) == round(best - current, 1)


def test_roster_rows_mark_starters_and_bench() -> None:
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"])],
    )
    rows = [c.columns for c in _provider(client).roster("L1")]
    assert {r["Player"]: r["Slot"] for r in rows} == {"Star QB": "START", "Good RB": "BN"}


def test_roster_rows_skip_players_missing_from_the_catalog() -> None:
    client = FakeSleeper(rosters=[SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["ghost"], starter_ids=[])])
    assert _provider(client).roster("L1") == []


# ── headline figures ────────────────────────────────────────────────────


def test_the_header_carries_the_weeks_standing() -> None:
    context = _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1")
    labels = {stat.label: stat.value for stat in context.headline}

    assert labels["Week"] == "3"
    assert labels["Record"] == "2-1"
    assert labels["Points for"] == "250.5"


def test_the_header_agrees_with_the_prompt_about_the_lineup_total() -> None:
    """Two numbers for the same thing, differing in the last decimal, reads as
    a bug even when neither is wrong."""
    context = _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1")
    lineup = next(stat for stat in context.headline if stat.label == "Lineup")

    assert f"Current lineup projects {lineup.value} points" in context.constraints


def test_the_header_carries_the_matchup() -> None:
    """The question the page is opened to answer: who, and am I ahead."""
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 71.0},
        ],
    )
    labels = {s.label: s for s in _provider(client).build_context("L1").headline}

    assert "Opponent" in labels
    assert labels["Live"].value == "88.5 – 71.0"
    assert (labels["Margin"].value, labels["Margin"].tone) == ("+17.5", "good")


def test_trailing_is_the_figure_that_warns() -> None:
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 60.0},
            {"roster_id": 2, "matchup_id": 7, "points": 84.0},
        ],
    )
    margin = next(s for s in _provider(client).build_context("L1").headline if s.label == "Margin")

    assert (margin.value, margin.tone) == ("-24.0", "warning")


def test_a_week_with_no_opponent_reports_no_matchup_figures() -> None:
    """A bye or a missing scoreboard is not a 0-0 scoreline."""
    labels = {s.label for s in _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1").headline}

    assert "Margin" not in labels
    assert "Week" in labels  # the rest of the header still stands


def test_the_matchup_is_fetched_once_for_both_the_prompt_and_the_header() -> None:
    """Deriving them separately would pull the scoreboard twice per report, and
    the scoreboard is the one thing here that changes minute to minute."""
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 71.0},
        ],
    )
    context = _provider(client).build_context("L1")

    assert client.matchup_fetches == 1
    assert "OPPONENT:" in context.situation
    assert any(s.label == "Opponent" for s in context.headline)


# ── the summary, before any report ──────────────────────────────────────


def test_the_summary_carries_the_lineup_and_the_changes() -> None:
    """Every figure in it is already known, so the page need not wait on a model."""
    summary = _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).summary("L1")

    assert [spot.slot for spot in summary.mine.lineup] == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    assert any(stat.label == "Week" for stat in summary.headline)


def test_a_player_with_no_game_is_flagged_while_others_have_one() -> None:
    summary = _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).summary("L1")
    benched = {spot.player: spot for spot in summary.mine.lineup + summary.mine.bench}

    assert benched["Star QB"].tone == "neutral"  # has an opponent


def test_a_week_nobody_is_scheduled_for_does_not_flag_the_whole_roster() -> None:
    """Before the season opens Sleeper publishes no fixtures, and warning on
    every player turns the page amber over a date rather than a decision."""
    preseason = {pid: _proj(pid, proj.name, proj.position, 0.0, opp="") for pid, proj in DEFAULT_PROJECTIONS.items()}
    summary = _provider(FakeSleeper(projections=preseason)).summary("L1")

    assert all(spot.tone == "neutral" for spot in summary.mine.lineup if spot.player != "—")
    assert all("not scheduled yet" in spot.detail for spot in summary.mine.lineup if spot.player != "—")


def test_the_summary_does_not_ask_for_the_waiver_pool() -> None:
    """It is the expensive half of a report and nothing in the header uses it."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS)
    client.get_trending = lambda *a, **k: pytest.fail("summary must not fetch trending")  # type: ignore[method-assign]

    client_summary = _provider(client).summary("L1")

    assert client_summary.headline


def test_the_week_shows_the_team_you_are_playing() -> None:
    """The other half of the only question a week asks."""
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"], wins=2, losses=1
            ),
            SleeperRoster(roster_id=2, owner_id="them", player_ids=["rb2", "wr9"], starter_ids=["wr9"], wins=3),
        ],
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 96.1},
        ],
    )
    summary = _provider(client).summary("L1")

    assert summary.opponent is not None
    assert [spot.player for spot in summary.opponent.lineup] == ["Waiver WR"]
    assert [spot.player for spot in summary.opponent.bench] == ["Bad RB"]
    assert summary.opponent.points == "96.1"


def test_a_week_with_no_fixture_shows_no_opponent() -> None:
    """A bye is not a nil-nil scoreline."""
    assert _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).summary("L1").opponent is None


def test_a_bye_is_reported_once_per_club_not_once_per_player() -> None:
    byes = {stat.label for stat in _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).summary("L1").fixtures}
    assert byes == set()  # every fake projection has an opponent


def test_a_player_carries_their_week_and_their_depth() -> None:
    detail = _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "qb1")
    labels = {stat.label: stat.value for group in detail.groups for stat in group.stats}

    assert detail.name == "Star QB"
    assert detail.headline == "22.0"
    assert detail.headline_label == "projected for week 3"
    assert labels["Opponent"] == "vs MIA"


def test_an_unknown_player_is_refused() -> None:
    with pytest.raises(PlayerNotFoundError):
        _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "nobody")


def test_a_projection_is_broken_out_into_the_line_behind_it() -> None:
    """The total is what a lineup is chosen on; this is what makes it believable."""
    projections = {
        "qb1": WeeklyProjection(
            player_id="qb1",
            name="Star QB",
            position="QB",
            team="BUF",
            opponent="MIA",
            points=22.0,
            stats={"pass_yd": 271.0, "pass_td": 1.8, "rush_yd": 18.0, "rec": 0.0},
        )
    }
    groups = {g.title: g for g in _provider(FakeSleeper(projections=projections)).player("L1", "qb1").groups}

    line = {s.label: s.value for s in groups["Projected line"].stats}
    assert line["Pass yards"] == "271"
    assert "Receptions" not in line  # a zero for a quarterback is noise


def test_a_player_with_no_projection_has_no_line_to_break_out() -> None:
    titles = [g.title for g in _provider(FakeSleeper()).player("L1", "qb1").groups]
    assert "Projected line" not in titles


# ── the seasons behind the projection ───────────────────────────────────


def _stats(pid: str, season: str, *, games: int, ppr: float, rank: int = 0, **splits: float) -> SeasonStats:
    return SeasonStats(
        player_id=pid,
        season=season,
        games=games,
        points={"pts_ppr": ppr, "pts_half_ppr": ppr - 10, "pts_std": ppr - 20},
        position_rank=rank,
        splits=splits,
    )


HISTORY = {
    "2025": {"qb1": _stats("qb1", "2025", games=16, ppr=320.0, rank=4, pass_yd=4200.0, pass_td=30.0)},
    "2024": {"qb1": _stats("qb1", "2024", games=12, ppr=210.0, rank=14, pass_yd=2800.0, pass_td=18.0)},
}


def _table(client: FakeSleeper, player_id: str = "qb1") -> dict[str, Any]:
    """The by-season table as {row label: values}, columns newest first."""
    table = _provider(client).player("L1", player_id).tables[0]
    return {"__columns__": table.columns, **{row.label: row.values for row in table.rows}}


def test_the_seasons_are_columns_so_they_can_be_read_across() -> None:
    """A stack makes you hold last year's yards in your head while scrolling
    to this year's."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)

    assert _table(client)["__columns__"] == ["2026", "2025", "2024"]


def test_a_season_nobody_has_played_yet_reports_nothing() -> None:
    """The fake sits in the regular season but has no 2026 totals, which is
    every August: a column of noughts claims answers it does not have."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)

    table = _table(client)
    assert table["Total"][0] == "N/A"
    assert table["Games"][0] == "N/A"


def test_a_finished_season_is_scored_per_game_not_only_as_a_total() -> None:
    """A total mostly measures availability: 12 games is not a worse week."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)

    table = _table(client)
    assert table["Per game"][2] == f"{210.0 / 12:.1f}"
    assert table["Games"][2] == "12"


def test_a_season_is_scored_in_the_leagues_own_currency() -> None:
    """75 receptions is 37.5 points between full PPR and standard."""
    league = SleeperLeague(
        league_id="L1",
        name="Sunday Money",
        season="2026",
        total_rosters=12,
        scoring_format="pts_std",
        roster_positions=["QB", "RB", "BN"],
    )
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY, league=league)

    assert _table(client)["Total"][1] == "300.0"  # pts_std, not pts_ppr


def test_a_split_a_position_never_records_has_no_row_at_all() -> None:
    """A running back has no completion percentage, and a whole row of N/A is
    a row of nothing."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats=HISTORY)

    table = _table(client)
    assert "Passing yards" in table
    assert "Receptions" not in table


def test_a_rookie_gets_no_table_rather_than_a_table_of_nothing() -> None:
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats={})

    assert _provider(client).player("L1", "qb1").tables == []


def test_a_failed_history_lookup_does_not_take_the_player_down() -> None:
    """The week was already fetched and is still true."""
    client = FakeSleeper(projections=DEFAULT_PROJECTIONS, season_stats_error=SleeperAPIError("down"))

    detail = _provider(client).player("L1", "qb1")

    assert detail.name == "Star QB"
    assert detail.tables == []


def test_a_player_carries_a_portrait_from_sleepers_own_cdn() -> None:
    detail = _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).player("L1", "qb1")

    assert detail.image_url.endswith("/qb1.jpg")


# ── the league beyond this week ─────────────────────────────────────────


def _sched(week: int, day: str, home: str, away: str) -> ScheduledGame:
    return ScheduledGame(week=week, date=day, home=home, away=away)


SEASON_SCHEDULE = [
    _sched(1, "2026-09-10", "KC", "BAL"),
    _sched(1, "2026-09-13", "DAL", "NYG"),
    _sched(1, "2026-09-14", "SF", "SEA"),
    _sched(2, "2026-09-17", "MIA", "BUF"),
]


def _league_client(**extra: Any) -> FakeSleeper:
    return FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        season_schedule=SEASON_SCHEDULE,
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"], wins=2),
            SleeperRoster(roster_id=2, owner_id="them", player_ids=["rb2"], starter_ids=["rb2"], wins=3),
        ],
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 96.1},
        ],
        **extra,
    )


def test_the_season_spans_every_regular_season_week() -> None:
    season = _provider(_league_client()).schedule("L1").season
    assert [row.label for row in season[:3]] == ["Week 1", "Week 2", "Week 3"]
    assert len(season) == 18


def test_a_week_carries_the_days_it_is_actually_played() -> None:
    """An NFL week runs Thursday to Monday, so one date is wrong for most of it."""
    season = _provider(_league_client()).schedule("L1").season
    assert season[0].date == "10-14 Sep"


def test_a_future_week_has_no_score() -> None:
    """A week that has not happened is not nil-nil."""
    season = _provider(_league_client()).schedule("L1").season
    assert season[5].result == ""
    assert season[5].tone == "neutral"


def test_a_played_week_carries_its_score_and_whether_it_was_won() -> None:
    season = _provider(_at_week(5)).schedule("L1").season

    assert season[0].result == "88.5-96.1"
    assert season[0].tone == "warning"  # 88.5 lost


def test_the_current_week_is_marked() -> None:
    season = _provider(_league_client()).schedule("L1").season
    assert [row.label for row in season if row.is_current] == ["Week 3"]


def test_the_table_is_sorted_on_the_record_and_says_which_is_yours() -> None:
    standings = _provider(_league_client()).schedule("L1").standings
    assert [row.rank for row in standings] == [1, 2]
    assert standings[0].record == "3-0"  # the 3-win roster leads
    assert [row.is_mine for row in standings] == [False, True]


def _at_week(week: int, **extra: Any) -> FakeSleeper:
    client = _league_client(**extra)
    client.get_state = lambda sport="nfl": SeasonState(  # type: ignore[method-assign]
        week=week, season="2026", season_type="regular"
    )
    return client


def test_the_real_games_behind_the_week_are_listed_with_their_day() -> None:
    matches = _provider(_at_week(2)).schedule("L1").matches
    assert [(m.away, m.home) for m in matches] == [("BUF", "MIA")]
    assert matches[0].label == "Thu 17 Sep"


def test_a_week_with_no_real_games_lists_none() -> None:
    """The default fake season only reaches week 2."""
    assert _provider(_league_client()).schedule("L1").matches == []


def test_a_game_you_have_players_in_is_marked() -> None:
    """The only thing that makes one game on a slate different from another."""
    matches = _provider(_at_week(2)).schedule("L1").matches
    marked = {(m.away, m.home) for m in matches if m.detail}

    assert marked == {("BUF", "MIA")}  # every fake projection is a BUF player


def test_activity_is_newest_first_on_the_instant_not_the_label() -> None:
    """ "Sep 3" sorts before "Sep 21" alphabetically and after it in time."""
    client = _at_week(
        2,
        transactions={
            1: [Transaction(kind="waiver", roster_ids=[1], adds={"qb1": 1}, drops={}, when=1_756_000_000_000)],
            2: [Transaction(kind="trade", roster_ids=[2], adds={}, drops={"rb2": 2}, when=1_759_000_000_000)],
        },
    )

    activity = _provider(client).schedule("L1").activity

    assert [row.what for row in activity] == ["Trade", "Waiver"]


def test_activity_names_players_rather_than_identifiers() -> None:
    client = _league_client(
        transactions={3: [Transaction(kind="waiver", roster_ids=[1], adds={"qb1": 1}, drops={"rb1": 1}, when=1)]}
    )

    activity = _provider(client).schedule("L1").activity

    assert activity[0].detail == "+Star QB, -Good RB"
    assert activity[0].tone == "good"  # it was mine


def test_a_failed_activity_fetch_leaves_the_rest_of_the_page() -> None:
    schedule = _provider(_league_client(transactions_error=SleeperAPIError("down"))).schedule("L1")

    assert schedule.activity == []
    assert schedule.standings


def test_dates_are_enrichment_not_a_reason_to_fail() -> None:
    """A week without them is still a week."""
    schedule = _provider(_league_client(schedule_error=SleeperAPIError("down"))).schedule("L1")

    assert schedule.season
    assert schedule.season[0].date == ""
    assert schedule.matches == []


def test_the_week_says_when_it_is_played() -> None:
    """A week with no dates on it is a number, which is already known."""
    assert _provider(_league_client()).summary("L1").window == "Week 3"


def test_the_window_carries_the_dates_where_there_are_any() -> None:
    assert _provider(_at_week(2)).summary("L1").window == "Week 2 · 17 Sep"


# ── reading the two lineups across ──────────────────────────────────────

FULL_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN"]
FULL_PROJECTIONS = {
    "qb1": _proj("qb1", "Star QB", "QB", 22.0),
    "rb1": _proj("rb1", "Good RB", "RB", 18.0),
    "rb2": _proj("rb2", "Bad RB", "RB", 4.0),
    "wr1": _proj("wr1", "WR One", "WR", 15.0),
    "wr2": _proj("wr2", "WR Two", "WR", 12.0),
    "te1": _proj("te1", "The TE", "TE", 9.0),
    "fx1": _proj("fx1", "Flex WR", "WR", 8.0),
    "k1": _proj("k1", "The K", "K", 7.0),
    "def1": _proj("def1", "The D", "DEF", 6.0),
}
FULL_STARTERS = ["qb1", "rb1", "rb2", "wr1", "wr2", "te1", "fx1", "k1", "def1"]


def _full_league() -> SleeperLeague:
    return SleeperLeague(
        league_id="L1",
        name="Sunday Money",
        season="2026",
        total_rosters=12,
        scoring_format="pts_ppr",
        roster_positions=FULL_SLOTS,
    )


def _both_sides() -> FakeSleeper:
    return FakeSleeper(
        projections=FULL_PROJECTIONS,
        league=_full_league(),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=FULL_STARTERS, starter_ids=FULL_STARTERS),
            SleeperRoster(roster_id=2, owner_id="them", player_ids=FULL_STARTERS, starter_ids=FULL_STARTERS),
        ],
        matchups=[{"roster_id": 1, "matchup_id": 7}, {"roster_id": 2, "matchup_id": 7, "points": 96.1}],
    )


def test_both_lineups_are_listed_in_the_same_slot_order() -> None:
    """The sides are read across, so an opponent in roster order is not a
    comparison — Sleeper returns `player_ids` in no order at all."""
    summary = _provider(_both_sides()).summary("L1")

    assert summary.opponent is not None
    slots = [spot.slot for spot in summary.opponent.lineup]
    assert slots == [spot.slot for spot in summary.mine.lineup]
    assert slots == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


def test_an_off_length_starter_list_is_left_unlabelled() -> None:
    """Positions cannot be trusted once the lists disagree, and a WR labelled
    QB is worse than a row carrying no label at all."""
    client = _both_sides()
    client.rosters[1] = SleeperRoster(roster_id=2, owner_id="them", player_ids=FULL_STARTERS, starter_ids=["wr1"])

    summary = _provider(client).summary("L1")

    assert summary.opponent is not None
    assert [spot.slot for spot in summary.opponent.lineup] == [""]


def test_a_slot_does_not_repeat_the_position_beside_it() -> None:
    """The slot column already says QB; saying it twice reads as two facts."""
    summary = _provider(_both_sides()).summary("L1")

    quarterback = summary.mine.lineup[0]
    assert quarterback.slot == "QB"
    assert not quarterback.detail.startswith("QB")


def test_a_flex_still_says_which_position_is_filling_it() -> None:
    """The one case where place and position genuinely differ."""
    summary = _provider(_both_sides()).summary("L1")

    flex = next(spot for spot in summary.mine.lineup if spot.slot == "FLEX")
    assert flex.detail.startswith("WR")


# ── the week as it is actually going ────────────────────────────────────
# Not reachable with live data outside the season, so the shape of a week in
# progress is only ever exercised here.

KICKED_OFF = [
    ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="complete"),
    ScheduledGame(week=3, date="2026-09-28", home="KC", away="DEN", status="pre_game"),
]


def _live_client(points: dict[str, float]) -> FakeSleeper:
    return FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        season_schedule=KICKED_OFF,
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
        matchups=[{"roster_id": 1, "matchup_id": 4, "players_points": points}],
    )


def test_a_player_whose_game_has_started_shows_what_they_scored() -> None:
    """Every fake projection is a BUF player, and BUF has finished."""
    summary = _provider(_live_client({"qb1": 24.5, "rb2": 3.0})).summary("L1")

    values = {spot.player: spot.value for spot in summary.mine.lineup}
    assert values["Star QB"] == "24.5 pts"


def test_a_haul_and_a_blank_are_toned_apart() -> None:
    summary = _provider(_live_client({"qb1": 24.5, "rb2": 3.0})).summary("L1")

    tones = {spot.player: spot.tone for spot in summary.mine.lineup}
    assert tones["Star QB"] == "good"
    assert tones["Bad RB"] == "warning"


def test_a_player_whose_game_has_not_kicked_off_keeps_their_projection() -> None:
    """Nought against somebody playing on Monday says they blanked."""
    client = _live_client({"qb1": 0.0})
    client.season_schedule = [ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="pre_game")]

    summary = _provider(client).summary("L1")

    assert all(not spot.value.endswith("pts") for spot in summary.mine.lineup)


def test_the_side_total_switches_from_projected_to_scored() -> None:
    assert _provider(_live_client({"qb1": 24.5, "rb2": 3.0})).summary("L1").mine.points == "27.5 pts"


def test_before_kickoff_the_side_total_is_still_a_projection() -> None:
    client = _live_client({})
    client.season_schedule = [ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA", status="pre_game")]

    assert _provider(client).summary("L1").mine.points.endswith("proj")


def test_a_missing_scoreboard_falls_back_to_projections() -> None:
    client = _live_client({})
    client.matchups_error = SleeperAPIError("down")

    summary = _provider(client).summary("L1")

    assert summary.mine is not None
    assert summary.mine.points.endswith("proj")


# ── the rest of the league ──────────────────────────────────────────────


def test_the_teams_list_puts_you_first() -> None:
    """You are the row somebody is looking for, and a fourteen-team league is
    long enough that hunting for it is a chore."""
    teams = _provider(_league_client()).teams("L1")

    assert teams[0].is_mine
    assert [t.is_mine for t in teams[1:]] == [False]


def test_a_team_carries_the_id_its_roster_is_behind() -> None:
    teams = _provider(_league_client()).teams("L1")
    assert {t.team_id for t in teams} == {"1", "2"}


def test_another_managers_roster_comes_back_in_your_own_columns() -> None:
    """One table renders both, so they have to agree about the shape."""
    provider = _provider(_league_client())

    mine = provider.roster("L1")
    theirs = provider.roster_of("L1", "2")

    assert set(theirs[0].columns) == set(mine[0].columns)
    assert [c.columns["Player"] for c in theirs] == ["Bad RB"]


def test_an_unknown_team_is_refused() -> None:
    with pytest.raises(TeamNotFoundError):
        _provider(_league_client()).roster_of("L1", "999")


def test_free_agents_exclude_everyone_already_rostered() -> None:
    client = _league_client()
    client.players_catalog = {
        "qb1": PlayerMeta(player_id="qb1", name="Star QB", position="QB", team="BUF"),
        "free1": PlayerMeta(player_id="free1", name="Waiver WR", position="WR", team="NYJ"),
    }

    agents = _provider(client).free_agents("L1")

    assert [c.columns["Player"] for c in agents] == ["Waiver WR"]


def test_a_position_a_fantasy_league_does_not_score_is_left_out() -> None:
    """The catalog carries every practice-squad body in the league."""
    client = _league_client()
    client.players_catalog = {
        "ol1": PlayerMeta(player_id="ol1", name="A Guard", position="OL", team="NYJ"),
        "free1": PlayerMeta(player_id="free1", name="Waiver WR", position="WR", team="NYJ"),
    }

    agents = _provider(client).free_agents("L1")

    assert [c.columns["Player"] for c in agents] == ["Waiver WR"]


def test_free_agents_have_no_lineup_column() -> None:
    """It would read "BN" down its whole length."""
    client = _league_client()
    client.players_catalog = {"free1": PlayerMeta(player_id="free1", name="Waiver WR", position="WR", team="NYJ")}

    assert "Slot" not in _provider(client).free_agents("L1")[0].columns


# ── the one figure a player is judged on ────────────────────────────────


def test_a_player_with_no_projection_has_no_figure_at_all() -> None:
    """Not the string "no projection", which renders as though the absence of
    a number were the number."""
    client = FakeSleeper(projections={})

    detail = _provider(client).player("L1", "qb1")

    assert detail.headline == ""


def test_nothing_published_yet_reads_differently_from_not_featuring() -> None:
    """A reader can act on the difference: the league has not posted week 3,
    versus it has and this player is not in it."""
    unpublished = _provider(FakeSleeper(projections={})).player("L1", "qb1")

    scheduled = FakeSleeper(projections={"rb1": _proj("rb1", "Good RB", "RB", 18.0)})
    benched = _provider(scheduled).player("L1", "qb1")

    assert "not published yet" in unpublished.headline_label
    assert "Not projected to feature" in benched.headline_label
