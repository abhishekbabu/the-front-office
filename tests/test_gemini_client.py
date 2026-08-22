"""Tests for GeminiClient's mock mode — the path `--mock` exercises."""

import pytest

from the_front_office.clients.gemini.client import GeminiClient
from the_front_office.clients.gemini.constants import MODEL_FLASH, MODEL_PRO
from the_front_office.clients.gemini.types import (
    MOCK_SCOUT_REPORT,
    MOCK_TRADE_REPORT,
    MockChatSession,
)
from the_front_office.exceptions import AIUnavailableError


def test_mock_mode_never_constructs_a_real_client() -> None:
    """--mock must not require GOOGLE_API_KEY or make a network call."""
    assert GeminiClient(mock_mode=True).client is None


def test_missing_api_key_raises_a_domain_error_not_a_string() -> None:
    """Callers must be able to distinguish 'no credentials' from a real report."""
    c = GeminiClient(api_key=None)
    assert c.client is None
    with pytest.raises(AIUnavailableError, match="--mock"):
        c.start_chat()


def test_mock_start_chat_returns_a_mock_session() -> None:
    chat = GeminiClient(mock_mode=True).start_chat()
    assert isinstance(chat, MockChatSession)
    assert chat.send_message("why this player?").text is not None


def test_first_mock_message_returns_a_report_shaped_reply() -> None:
    """Regression: --scout --mock used to answer the analysis prompt with a
    generic follow-up line, so it exercised none of the report path."""
    chat = MockChatSession()
    report = chat.send_message("You are an elite NBA Fantasy GM ... REPORT FORMAT:").text
    assert report == MOCK_SCOUT_REPORT
    assert "Scout Report" in (report or "")


def test_trade_prompt_gets_the_trade_shaped_reply() -> None:
    chat = MockChatSession()
    report = chat.send_message("# Trade Evaluation Request\n**Giving Away:** X").text
    assert report == MOCK_TRADE_REPORT
    assert "Verdict" in (report or "")


def test_followups_after_the_report_are_short_canned_replies() -> None:
    chat = MockChatSession()
    chat.send_message("initial analysis prompt")
    followup = chat.send_message("why that player?").text or ""
    assert followup.startswith("[MOCK]")
    assert followup != MOCK_SCOUT_REPORT


def test_mock_trade_parse_yields_a_valid_proposal() -> None:
    proposal = GeminiClient(mock_mode=True).parse_trade_string("anything at all")
    assert proposal.is_valid
    assert proposal.giving and proposal.receiving


def test_parsing_uses_flash_and_strategy_uses_pro() -> None:
    """Flash for high-volume parsing, Pro for strategy — per project_spec.md."""
    import inspect

    from the_front_office.clients.gemini import client as mod

    assert MODEL_FLASH == "gemini-2.5-flash"
    assert MODEL_PRO == "gemini-2.5-pro"
    assert "MODEL_FLASH" in inspect.getsource(mod.GeminiClient.parse_trade_string)
    assert "MODEL_PRO" in inspect.getsource(mod.GeminiClient.start_chat)
