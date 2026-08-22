"""Tests for the Sleeper football provider."""

from typing import Any

import pytest

from the_front_office.clients.sleeper.types import (
    NFLState,
    PlayerMeta,
    Projection,
    SleeperLeague,
    SleeperRoster,
    SleeperUser,
    TrendingPlayer,
)
from the_front_office.exceptions import LeagueNotFoundError, SleeperAPIError
from the_front_office.sports.nfl.provider import NFLProvider

MY_ID = "user-1"


def _proj(pid: str, name: str, pos: str, pts: float, team: str = "BUF", opp: str = "MIA") -> Projection:
    return Projection(player_id=pid, name=name, position=pos, team=team, opponent=opp, points=pts)


class FakeSleeper:
    """Stands in for SleeperClient."""

    def __init__(
        self,
        rosters: list[SleeperRoster] | None = None,
        projections: dict[str, Projection] | None = None,
        league: SleeperLeague | None = None,
        matchups: list[dict[str, Any]] | None = None,
        trending: list[TrendingPlayer] | None = None,
        trending_error: Exception | None = None,
    ) -> None:
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

    def get_nfl_state(self) -> NFLState:
        return NFLState(week=3, season="2026", season_type="regular", display_week=3)

    def get_user(self, username: str) -> SleeperUser:
        return SleeperUser(user_id=MY_ID, username=username, display_name=username)

    def get_leagues(self, user_id: str, season: str) -> list[SleeperLeague]:
        return [self.league]

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        return self.rosters

    def get_league_users(self, league_id: str) -> dict[str, str]:
        return {MY_ID: "Me", "user-2": "Rival"}

    def get_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        return self.matchups

    def get_players(self) -> dict[str, PlayerMeta]:
        return {
            "qb1": PlayerMeta(player_id="qb1", name="Star QB", position="QB", team="BUF"),
            "rb1": PlayerMeta(player_id="rb1", name="Good RB", position="RB", team="BUF"),
            "rb2": PlayerMeta(player_id="rb2", name="Bad RB", position="RB", team="BUF"),
            "wr9": PlayerMeta(player_id="wr9", name="Waiver WR", position="WR", team="NYJ"),
            "bye1": PlayerMeta(player_id="bye1", name="Bye Guy", position="TE", team="LAR"),
        }

    def get_projections(self, season: str, week: int, scoring: str) -> dict[str, Projection]:
        return self.projections

    def get_trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list[TrendingPlayer]:
        if self.trending_error:
            raise self.trending_error
        return self.trending


def _provider(client: FakeSleeper) -> NFLProvider:
    return NFLProvider(username="me", client=client)  # type: ignore[arg-type]


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
    provider = NFLProvider(username=None, client=FakeSleeper())  # type: ignore[arg-type]
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


def test_squad_and_available_players_are_separated() -> None:
    ctx = _context()
    assert "Star QB" in ctx.squad_lines
    assert "Waiver WR" in ctx.candidate_lines
    assert "Waiver WR" not in ctx.squad_lines


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
    drop the player from the squad."""
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "bye1"], starter_ids=["qb1"])],
    )
    ctx = _provider(client).build_context("L1")
    assert "Bye Guy" in ctx.squad_lines
    assert "0.0 proj pts" in ctx.squad_lines["Bye Guy"]
    assert "(no game)" in ctx.squad_lines["Bye Guy"]


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
    assert ctx.squad_lines  # the rest still built


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
    """Regression: the optimal lineup was labelled as the current one, so a
    player could appear in the lineup block and the bench block at once."""
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
    """Regression: the delta was computed from unrounded points while the totals
    were printed rounded, so the prompt could show 124.1 - 121.4 = 2.8."""
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
