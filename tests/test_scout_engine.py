"""Tests for the Scout orchestrator.

Exercises the prompt-building logic, which is where league rules (add budget,
IL slots, matchup context) actually get encoded.
"""

from typing import Any

import pytest
from conftest import FakeAI, FakeNBA, FakeYahoo, make_player

from the_front_office.exceptions import TeamNotFoundError
from the_front_office.report.engine import ScoutEngine
from the_front_office.report.mocks import MOCK_SCOUT_REPORT
from the_front_office.report.types import ScoutReport
from the_front_office.sports.nba.provider import NBAProvider


def _scout(yahoo: FakeYahoo, ai: FakeAI | None = None, nba: FakeNBA | None = None) -> ScoutEngine:
    provider = NBAProvider(league=None, nba=nba or FakeNBA(), yahoo=yahoo)  # type: ignore[arg-type]
    return ScoutEngine(provider, ai=ai or FakeAI())  # type: ignore[arg-type]


def test_returns_a_validated_report_and_an_open_chat() -> None:
    ai = FakeAI()
    report, chat = _scout(FakeYahoo(), ai=ai).start_analysis("")
    assert isinstance(report, ScoutReport)
    assert report == MOCK_SCOUT_REPORT
    assert chat is ai.chat


def test_follow_up_chat_is_seeded_with_the_report() -> None:
    """Follow-ups must see the analysis without re-sending the whole context."""
    ai = FakeAI()
    _scout(FakeYahoo(), ai=ai).start_analysis("")
    roles = [item["role"] for item in ai.history]
    assert roles == ["user", "model"]
    # The model turn is the report itself, as JSON the follow-up can reason over.
    assert ScoutReport.model_validate_json(ai.history[1]["parts"][0]) == MOCK_SCOUT_REPORT


def test_follow_up_is_seeded_with_a_briefing_not_the_whole_prompt() -> None:
    """The history is resent on every follow-up, so the prompt's free-agent
    block — over half its volume — must not ride along."""
    ai = FakeAI()
    _scout(_rich_yahoo(), ai=ai).start_analysis("")
    briefing, prompt = ai.history[0]["parts"][0], ai.prompts[0]

    assert len(briefing) < len(prompt) / 2
    assert "LEAGUE RULES" not in briefing  # generation-time instructions
    assert "YOUR TASK" not in briefing


def test_briefing_keeps_what_a_follow_up_needs() -> None:
    ai = FakeAI()
    _scout(_rich_yahoo(), ai=ai).start_analysis("")
    briefing = ai.history[0]["parts"][0]

    assert "CURRENT MATCHUP" in briefing  # why a category is close
    assert "TRANSACTION CONTEXT" in briefing  # why only three adds
    assert "CURRENT SQUAD" in briefing  # why that drop
    assert "Roster Player 0" in briefing


def test_briefing_carries_only_the_recommended_free_agents() -> None:
    """_rich_yahoo offers nine free agents; the canned report names one."""
    ai = FakeAI()
    recommended = MOCK_SCOUT_REPORT.moves[0].player
    _scout(_rich_yahoo(recommended=recommended), ai=ai).start_analysis("")
    briefing = ai.history[0]["parts"][0]

    assert recommended in briefing
    assert "Free Agent 7" not in briefing
    assert "Free Agent 3" not in briefing


def test_briefing_tells_the_model_the_list_is_partial() -> None:
    """Otherwise it would invent numbers for a player it can no longer see."""
    ai = FakeAI()
    _scout(_rich_yahoo(), ai=ai).start_analysis("")
    assert "re-run the report" in ai.history[0]["parts"][0]


def test_matchup_is_fetched_once_not_twice() -> None:
    """get_matchup_context and get_matchup_dates each used to sync their own Week."""
    yahoo = _rich_yahoo()
    _scout(yahoo).start_analysis("")
    assert yahoo.matchup_fetches == 1


def test_missing_team_raises_before_any_ai_call() -> None:
    """A billed Gemini call for a league we do not play in is pure waste."""

    class NoTeam(FakeYahoo):
        def get_user_team(self) -> Any:
            raise TeamNotFoundError("Some League")

    ai = FakeAI()
    with pytest.raises(TeamNotFoundError):
        _scout(NoTeam(), ai=ai).start_analysis("")
    assert ai.prompts == []


# ── prompt content ──────────────────────────────────────────────────────


def _rich_yahoo(recommended: str = "Mock Player One") -> FakeYahoo:
    """A league with a full roster and several free agents, one of which the
    canned report recommends."""
    roster = [make_player(f"Roster Player {i}", key=f"r{i}") for i in range(10)]
    fas = [make_player(f"Free Agent {i}", key=f"fa{i}") for i in range(8)]
    fas.append(make_player(recommended, key="rec"))
    return FakeYahoo(roster=roster, stat_leaders={"BLK": fas, "REB": fas[:3]})


def _prompt_for(yahoo: FakeYahoo, nba: FakeNBA | None = None) -> str:
    ai = FakeAI()
    _scout(yahoo, ai=ai, nba=nba).start_analysis("")
    return ai.prompts[0]


def test_prompt_carries_roster_matchup_and_free_agents() -> None:
    yahoo = FakeYahoo(
        roster=[make_player("Roster One", team="LAL")],
        stat_leaders={"BLK": [make_player("Free Agent One", team="BOS", key="fa-1")]},
    )
    prompt = _prompt_for(yahoo)
    assert "Roster One" in prompt
    assert "Free Agent One" in prompt
    assert "CURRENT MATCHUP" in prompt


def test_free_agents_are_annotated_with_the_categories_they_lead() -> None:
    fa = make_player("Multi Cat", key="fa-1")
    yahoo = FakeYahoo(stat_leaders={"BLK": [fa], "REB": [fa]})
    prompt = _prompt_for(yahoo)
    assert "Top in: BLK, REB" in prompt


def test_free_agents_appearing_in_several_categories_are_listed_once_and_first() -> None:
    """Most versatile first: a two-category player outranks a one-category one."""
    multi = make_player("Multi Cat", key="multi")
    single = make_player("Single Cat", key="single")
    yahoo = FakeYahoo(stat_leaders={"BLK": [multi, single], "REB": [multi]})
    prompt = _prompt_for(yahoo)
    assert prompt.count("Multi Cat") == 1
    assert prompt.index("Multi Cat") < prompt.index("Single Cat")


def test_remaining_adds_drive_the_recommendation_instruction() -> None:
    with_adds = _prompt_for(FakeYahoo(adds_used=0))
    assert "Recommend **3 players** to add" in with_adds
    assert "Adds Used: 0/3" in with_adds


def test_exhausted_add_budget_switches_to_monitoring() -> None:
    """With no adds left the model must not recommend adds it cannot make."""
    exhausted = _prompt_for(FakeYahoo(adds_used=3))
    assert "0 adds remaining" in exhausted
    assert "MONITOR" in exhausted
    assert "Recommend **3 players** to add" not in exhausted


def test_add_budget_cannot_go_negative() -> None:
    """Yahoo can report more adds used than the configured weekly limit."""
    prompt = _prompt_for(FakeYahoo(adds_used=99))
    assert "Adds Used: 99/3" in prompt
    assert "Remaining Adds: 0" in prompt
    assert "Remaining Adds: -" not in prompt
    assert "0 adds remaining" in prompt  # and it switches to monitoring


def test_schedule_context_lists_teams_by_games_remaining() -> None:
    yahoo = FakeYahoo(
        roster=[make_player("Roster One", team="LAL")],
        stat_leaders={"BLK": [make_player("FA", team="BOS", key="fa")]},
    )
    nba = FakeNBA(games={"LAL": 2, "BOS": 4})
    prompt = _prompt_for(yahoo, nba=nba)
    assert "BOS: 4 games left" in prompt
    assert "LAL: 2 games left" in prompt
    assert prompt.index("BOS: 4") < prompt.index("LAL: 2")  # descending


def test_missing_matchup_dates_omit_the_schedule_block() -> None:
    prompt = _prompt_for(FakeYahoo(matchup_dates=("", "")))
    assert "REMAINING GAMES BY TEAM" not in prompt


def test_il_players_are_flagged_so_they_are_not_dropped_carelessly() -> None:
    yahoo = FakeYahoo(roster=[make_player("Hurt Star", selected_position="IL", status="O")])
    prompt = _prompt_for(yahoo)
    assert "[IN IL SPOT]" in prompt
    assert "[O]" in prompt
