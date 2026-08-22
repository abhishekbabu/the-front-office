"""Tests for GeminiClient's mock mode — the path `--mock` exercises."""

from the_front_office.clients.gemini.client import GeminiClient
from the_front_office.clients.gemini.constants import MODEL_FLASH, MODEL_PRO
from the_front_office.clients.gemini.types import MockChatSession


def test_mock_mode_never_constructs_a_real_client() -> None:
    """--mock must not require GOOGLE_API_KEY or make a network call."""
    assert GeminiClient(mock_mode=True).client is None


def test_missing_api_key_degrades_instead_of_raising() -> None:
    c = GeminiClient(api_key=None)
    assert c.client is None
    assert "Unavailable" in c.generate("anything")


def test_mock_start_chat_returns_a_mock_session() -> None:
    chat = GeminiClient(mock_mode=True).start_chat()
    assert isinstance(chat, MockChatSession)
    assert chat.send_message("why this player?").text is not None


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
    assert "MODEL_PRO" in inspect.getsource(mod.GeminiClient.generate)
