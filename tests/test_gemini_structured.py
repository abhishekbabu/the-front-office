"""Tests for GeminiClient's structured-generation paths, with a fake SDK client."""

from types import SimpleNamespace
from typing import Any

import pytest

from the_front_office.adapters.outbound.llm.gemini.client import GeminiClient
from the_front_office.adapters.outbound.llm.gemini.constants import MODEL_FLASH, MODEL_PRO
from the_front_office.domain.errors import AIResponseError, AIUnavailableError
from the_front_office.domain.mocks import MOCK_SCOUT_REPORT, MOCK_TRADE_VERDICT
from the_front_office.domain.models import ScoutReport, TradeVerdict


class FakeModels:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _client(response: Any = None, error: Exception | None = None) -> tuple[GeminiClient, FakeModels]:
    c = GeminiClient(api_key="fake-key")
    models = FakeModels(response, error)
    c.client = SimpleNamespace(models=models)  # type: ignore[assignment]
    return c, models


# ── generate_structured ─────────────────────────────────────────────────


def test_parsed_model_is_returned_directly() -> None:
    c, _ = _client(SimpleNamespace(parsed=MOCK_SCOUT_REPORT, text="{}"))
    assert c.generate_structured("p", ScoutReport) == MOCK_SCOUT_REPORT


def test_reports_use_pro_and_request_a_json_schema() -> None:
    c, models = _client(SimpleNamespace(parsed=MOCK_SCOUT_REPORT, text="{}"))
    c.generate_structured("p", ScoutReport)
    call = models.calls[0]
    assert call["model"] == MODEL_PRO
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["response_schema"] is ScoutReport


def test_raw_json_is_used_when_the_sdk_does_not_populate_parsed() -> None:
    """Guards against a client-library change degrading into a crash."""
    c, _ = _client(SimpleNamespace(parsed=None, text=MOCK_SCOUT_REPORT.model_dump_json()))
    assert c.generate_structured("p", ScoutReport) == MOCK_SCOUT_REPORT


def test_json_that_does_not_match_the_schema_raises() -> None:
    c, _ = _client(SimpleNamespace(parsed=None, text='{"matchup_insight": "x"}'))
    with pytest.raises(AIResponseError, match="failed validation"):
        c.generate_structured("p", ScoutReport)


def test_empty_response_raises() -> None:
    c, _ = _client(SimpleNamespace(parsed=None, text=""))
    with pytest.raises(AIResponseError, match="no usable"):
        c.generate_structured("p", ScoutReport)


def test_api_failure_is_wrapped_as_a_domain_error() -> None:
    c, _ = _client(error=RuntimeError("503 backend error"))
    with pytest.raises(AIResponseError, match="Gemini call failed"):
        c.generate_structured("p", ScoutReport)


def test_missing_credentials_raise_before_any_call() -> None:
    c = GeminiClient(api_key=None)
    with pytest.raises(AIUnavailableError):
        c.generate_structured("p", ScoutReport)


# ── structure_text ──────────────────────────────────────────────────────


def test_structuring_uses_flash_not_pro() -> None:
    """Converting prose is a parsing job — the cheap model, per project policy."""
    c, models = _client(SimpleNamespace(parsed=MOCK_TRADE_VERDICT, text="{}"))
    c.structure_text("some prose", TradeVerdict, instruction="Extract it.")
    assert models.calls[0]["model"] == MODEL_FLASH


def test_structuring_passes_the_prose_and_instruction_through() -> None:
    c, models = _client(SimpleNamespace(parsed=MOCK_TRADE_VERDICT, text="{}"))
    c.structure_text("VERDICT: accept", TradeVerdict, instruction="Extract it.")
    contents = models.calls[0]["contents"]
    assert "VERDICT: accept" in contents
    assert "Extract it." in contents
    assert "verbatim" in contents  # the do-not-editorialise instruction


def test_structuring_failure_is_wrapped() -> None:
    c, _ = _client(error=RuntimeError("bad request"))
    with pytest.raises(AIResponseError, match="Could not structure"):
        c.structure_text("prose", TradeVerdict, instruction="x")


def test_structuring_without_credentials_raises() -> None:
    c = GeminiClient(api_key=None)
    with pytest.raises(AIUnavailableError):
        c.structure_text("prose", TradeVerdict, instruction="x")


# ── parse_trade_string ──────────────────────────────────────────────────


def test_trade_parsing_returns_both_sides() -> None:
    c, _ = _client(SimpleNamespace(text='{"giving": ["A"], "receiving": ["B"]}'))
    proposal = c.parse_trade_string("Give A, Get B")
    assert proposal.giving == ["A"]
    assert proposal.receiving == ["B"]
    assert proposal.is_valid


def test_trade_parsing_coerces_a_bare_string_into_a_list() -> None:
    """The model sometimes returns a string when only one player is involved."""
    c, _ = _client(SimpleNamespace(text='{"giving": "A", "receiving": "B"}'))
    proposal = c.parse_trade_string("Give A, Get B")
    assert proposal.giving == ["A"]
    assert proposal.receiving == ["B"]


def test_trade_parsing_failure_raises() -> None:
    c, _ = _client(error=RuntimeError("boom"))
    with pytest.raises(AIResponseError, match="Trade parsing failed"):
        c.parse_trade_string("x")


def test_unparseable_json_raises_rather_than_returning_an_empty_trade() -> None:
    c, _ = _client(SimpleNamespace(text="not json at all"))
    with pytest.raises(AIResponseError):
        c.parse_trade_string("x")


# ── usage logging ───────────────────────────────────────────────────────


class Usage:
    prompt_token_count = 3400
    candidates_token_count = 310
    total_token_count = 3710
    cached_content_token_count = 0


def test_token_usage_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Gemini Pro on a large prompt is the only real expense; nothing else
    measures it."""
    c, _ = _client(SimpleNamespace(parsed=MOCK_SCOUT_REPORT, text="{}", usage_metadata=Usage()))
    with caplog.at_level("INFO"):
        c.generate_structured("p", ScoutReport)
    assert "3400 in" in caplog.text
    assert "310 out" in caplog.text
    assert MODEL_PRO in caplog.text


def test_structuring_logs_against_flash(caplog: pytest.LogCaptureFixture) -> None:
    c, _ = _client(SimpleNamespace(parsed=MOCK_TRADE_VERDICT, text="{}", usage_metadata=Usage()))
    with caplog.at_level("INFO"):
        c.structure_text("prose", TradeVerdict, instruction="x")
    assert MODEL_FLASH in caplog.text


def test_missing_usage_metadata_still_logs_latency(caplog: pytest.LogCaptureFixture) -> None:
    """An SDK change that drops usage_metadata must not break the call."""
    c, _ = _client(SimpleNamespace(parsed=MOCK_SCOUT_REPORT, text="{}"))
    with caplog.at_level("INFO"):
        c.generate_structured("p", ScoutReport)
    assert "no usage metadata" in caplog.text


def test_cached_tokens_are_reported_when_present(caplog: pytest.LogCaptureFixture) -> None:
    class Cached(Usage):
        cached_content_token_count = 1200

    c, _ = _client(SimpleNamespace(parsed=MOCK_SCOUT_REPORT, text="{}", usage_metadata=Cached()))
    with caplog.at_level("INFO"):
        c.generate_structured("p", ScoutReport)
    assert "1200 cached" in caplog.text
