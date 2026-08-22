"""Tests for the structured report schemas."""

import pytest
from google.genai import types as genai_types
from pydantic import ValidationError

from the_front_office.scout.types import MOCK_SCOUT_REPORT, Recommendation, ScoutReport
from the_front_office.trade.types import MOCK_TRADE_VERDICT, TradeVerdict

# Validated from dicts rather than constructors: the runtime rejection is the
# point, and a deliberately-invalid literal in a constructor call is a static
# type error the checker would (correctly) flag.
VALID_RECOMMENDATION: dict[str, object] = {
    "action": "ADD",
    "player_name": "Test Player",
    "position": "PF",
    "nba_team": "LAL",
    "games_remaining": 3,
    "categories_helped": ["REB"],
    "reasoning": "Rebounds at volume.",
    "drop_player": "Bench Guy",
    "drop_justification": "No categories won.",
}

VALID_VERDICT: dict[str, object] = {
    "verdict": "ACCEPT",
    "verdict_detail": "d",
    "categories_gained": ["REB"],
    "categories_lost": ["AST"],
    "impact": "i",
    "schedule_note": "s",
    "shutdown_risk": "r",
    "strategy": "st",
}


@pytest.mark.parametrize("schema", [ScoutReport, TradeVerdict])
def test_schemas_convert_for_the_gemini_response_schema(schema: type) -> None:
    """If genai cannot build a schema from the model, every report call fails."""
    genai_types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema)


def test_action_is_constrained_to_add_or_monitor() -> None:
    with pytest.raises(ValidationError):
        Recommendation.model_validate({**VALID_RECOMMENDATION, "action": "TRADE"})
    for ok in ("ADD", "MONITOR"):
        assert Recommendation.model_validate({**VALID_RECOMMENDATION, "action": ok}).action == ok


def test_verdict_is_constrained_to_the_three_outcomes() -> None:
    with pytest.raises(ValidationError):
        TradeVerdict.model_validate({**VALID_VERDICT, "verdict": "MAYBE"})
    for ok in ("ACCEPT", "REJECT", "COUNTER"):
        assert TradeVerdict.model_validate({**VALID_VERDICT, "verdict": ok}).verdict == ok


def test_missing_fields_are_rejected() -> None:
    """A model omitting a field must fail here, not render as a blank section."""
    with pytest.raises(ValidationError):
        ScoutReport.model_validate({"matchup_insight": "x", "close_categories": []})


def test_games_remaining_must_be_an_integer() -> None:
    with pytest.raises(ValidationError):
        Recommendation.model_validate({**VALID_RECOMMENDATION, "games_remaining": "four"})


def test_reports_round_trip_through_json() -> None:
    """start_analysis seeds the follow-up chat with model_dump_json()."""
    assert ScoutReport.model_validate_json(MOCK_SCOUT_REPORT.model_dump_json()) == MOCK_SCOUT_REPORT
    assert TradeVerdict.model_validate_json(MOCK_TRADE_VERDICT.model_dump_json()) == MOCK_TRADE_VERDICT


def test_every_field_carries_a_description_for_the_model() -> None:
    """Field descriptions are the schema's instructions to Gemini — a field
    without one gives the model nothing to go on."""
    for schema in (ScoutReport, Recommendation, TradeVerdict):
        undocumented = [n for n, f in schema.model_fields.items() if not f.description]
        assert not undocumented, f"{schema.__name__} fields missing descriptions: {undocumented}"


def test_mock_values_satisfy_their_own_schemas() -> None:
    """--mock must produce something the real code path would accept."""
    assert ScoutReport.model_validate(MOCK_SCOUT_REPORT.model_dump()) == MOCK_SCOUT_REPORT
    assert len(MOCK_SCOUT_REPORT.targets) == 3
    assert TradeVerdict.model_validate(MOCK_TRADE_VERDICT.model_dump()) == MOCK_TRADE_VERDICT
