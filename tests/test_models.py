"""Tests for the structured report schemas."""

import pytest
from google.genai import types as genai_types
from pydantic import ValidationError
from reports import MOCK_NBA_REPORT, MOCK_NBA_VERDICT

from thefrontoffice.domain.models import Move, ScoutReport, TradeProposal, TradeVerdict

# Validated from dicts rather than constructors: the runtime rejection is the
# point, and a deliberately-invalid literal in a constructor call is a static
# type error the checker would (correctly) flag.
VALID_MOVE: dict[str, object] = {
    "action": "ADD",
    "player": "Test Player",
    "position": "PF",
    "team": "LAL",
    "metric": "3 games left",
    "rationale": "Rebounds at volume.",
    "replaces": "Bench Guy",
    "replaces_rationale": "No categories won.",
}

VALID_VERDICT: dict[str, object] = {
    "verdict": "ACCEPT",
    "verdict_detail": "d",
    "gains": ["REB"],
    "losses": ["AST"],
    "impact": "i",
    "schedule": "s",
    "risk": "r",
    "strategy": "st",
}


@pytest.mark.parametrize("schema", [ScoutReport, TradeVerdict])
def test_schemas_convert_for_the_gemini_response_schema(schema: type) -> None:
    """If genai cannot build a schema from the model, every report call fails."""
    genai_types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema)


def test_action_is_constrained_to_add_or_monitor() -> None:
    with pytest.raises(ValidationError):
        Move.model_validate({**VALID_MOVE, "action": "NONSENSE"})
    for ok in ("ADD", "START", "BENCH", "TRANSFER", "CAPTAIN", "MONITOR", "DROP"):
        assert Move.model_validate({**VALID_MOVE, "action": ok}).action == ok


def test_verdict_is_constrained_to_the_three_outcomes() -> None:
    with pytest.raises(ValidationError):
        TradeVerdict.model_validate({**VALID_VERDICT, "verdict": "MAYBE"})
    for ok in ("ACCEPT", "REJECT", "COUNTER"):
        assert TradeVerdict.model_validate({**VALID_VERDICT, "verdict": ok}).verdict == ok


def test_missing_fields_are_rejected() -> None:
    """A model omitting a field must fail here, not render as a blank section."""
    with pytest.raises(ValidationError):
        ScoutReport.model_validate({"situation": "x", "focus": []})


def test_action_must_be_a_known_string() -> None:
    with pytest.raises(ValidationError):
        Move.model_validate({**VALID_MOVE, "action": 42})


def test_reports_round_trip_through_json() -> None:
    """start_analysis seeds the follow-up chat with model_dump_json()."""
    assert ScoutReport.model_validate_json(MOCK_NBA_REPORT.model_dump_json()) == MOCK_NBA_REPORT
    assert TradeVerdict.model_validate_json(MOCK_NBA_VERDICT.model_dump_json()) == MOCK_NBA_VERDICT


def test_every_field_carries_a_description_for_the_model() -> None:
    """Field descriptions are the schema's instructions to Gemini — a field
    without one gives the model nothing to go on."""
    for schema in (ScoutReport, Move, TradeVerdict):
        undocumented = [n for n, f in schema.model_fields.items() if not f.description]
        assert not undocumented, f"{schema.__name__} fields missing descriptions: {undocumented}"


def test_mock_values_satisfy_their_own_schemas() -> None:
    """--mock must produce something the real code path would accept."""
    assert ScoutReport.model_validate(MOCK_NBA_REPORT.model_dump()) == MOCK_NBA_REPORT
    assert len(MOCK_NBA_REPORT.moves) == 3
    assert TradeVerdict.model_validate(MOCK_NBA_VERDICT.model_dump()) == MOCK_NBA_VERDICT


# ── TradeProposal ───────────────────────────────────────────────────────


def test_both_sides_populated_is_valid() -> None:
    assert TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"]).is_valid


def test_one_sided_proposals_are_invalid() -> None:
    assert not TradeProposal(giving=["LeBron James"], receiving=[]).is_valid
    assert not TradeProposal(giving=[], receiving=["Jayson Tatum"]).is_valid


def test_empty_proposal_is_invalid() -> None:
    """This is what the AI parser returns when it fails, so it must be falsy."""
    assert not TradeProposal().is_valid


def test_defaults_are_not_shared_between_instances() -> None:
    a, b = TradeProposal(), TradeProposal()
    a.giving.append("LeBron James")
    assert b.giving == []
