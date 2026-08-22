"""Tests for GeminiClient's mock mode — the path `--mock` exercises."""

import pytest

from the_front_office.clients.gemini.client import GeminiClient
from the_front_office.clients.gemini.constants import MODEL_FLASH, MODEL_PRO
from the_front_office.clients.gemini.types import MockChatSession
from the_front_office.exceptions import AIResponseError, AIUnavailableError
from the_front_office.scout.types import MOCK_SCOUT_REPORT, ScoutReport
from the_front_office.trade.types import MOCK_TRADE_VERDICT, TradeVerdict


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


def test_mock_structured_generation_returns_the_canned_report() -> None:
    """--mock must exercise the real report path: a validated ScoutReport."""
    report = GeminiClient(mock_mode=True).generate_structured("any prompt", ScoutReport, mock=MOCK_SCOUT_REPORT)
    assert isinstance(report, ScoutReport)
    assert len(report.targets) == 3
    assert report.close_categories


def test_mock_structuring_returns_the_canned_verdict() -> None:
    verdict = GeminiClient(mock_mode=True).structure_text(
        "prose", TradeVerdict, instruction="extract", mock=MOCK_TRADE_VERDICT
    )
    assert isinstance(verdict, TradeVerdict)
    assert verdict.verdict == "ACCEPT"


def test_mock_without_a_canned_value_raises_rather_than_inventing_one() -> None:
    with pytest.raises(AIResponseError, match="ScoutReport"):
        GeminiClient(mock_mode=True).generate_structured("p", ScoutReport)


def test_mock_chat_only_answers_follow_ups() -> None:
    """Reports come from generate_structured now; the chat is follow-ups only."""
    chat = MockChatSession()
    assert (chat.send_message("why that player?").text or "").startswith("[MOCK]")
    assert (chat.send_message("and the next one?").text or "").startswith("[MOCK]")


def test_parsing_uses_flash_and_strategy_uses_pro() -> None:
    """Flash for high-volume parsing, Pro for strategy — per project_spec.md."""
    import inspect

    from the_front_office.clients.gemini import client as mod

    assert MODEL_FLASH == "gemini-2.5-flash"
    assert MODEL_PRO == "gemini-2.5-pro"
    assert "MODEL_FLASH" in inspect.getsource(mod.GeminiClient.parse_trade_string)
    assert "MODEL_PRO" in inspect.getsource(mod.GeminiClient.start_chat)
