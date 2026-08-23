"""Tests for the Gemini client's availability, and which model it uses where."""

import inspect

import pytest

from the_front_office.adapters.outbound.llm.gemini.client import GeminiClient
from the_front_office.adapters.outbound.llm.gemini.constants import MODEL_FLASH, MODEL_PRO
from the_front_office.domain.errors import AIUnavailableError
from the_front_office.domain.models import ScoutReport

# ── with no key, the app has nothing to offer ───────────────────────────


def test_without_a_key_no_client_is_constructed() -> None:
    """No network call, and nothing that could half-work."""
    assert GeminiClient(api_key=None).client is None


def test_availability_is_readable_before_anything_is_offered() -> None:
    """A button that explains why it cannot be pressed has wasted the click."""
    assert GeminiClient(api_key=None).is_available is False
    assert GeminiClient(api_key="a-key").is_available is True


def test_the_key_is_read_at_construction_not_bound_as_a_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key saved in Settings must take effect on the next call, not the next
    restart — a default argument is evaluated once, at import."""
    from the_front_office.config.settings import settings

    monkeypatch.setattr(settings, "gemini_api_key", "set-after-import")

    assert GeminiClient().is_available


def test_every_entry_point_refuses_the_same_way() -> None:
    """One domain error, so a caller never has to tell them apart."""
    client = GeminiClient(api_key=None)

    for call in (
        lambda: client.start_chat(),
        lambda: client.generate_structured("p", ScoutReport),
        lambda: client.parse_trade_string("Give A, Get B"),
    ):
        with pytest.raises(AIUnavailableError):
            call()


# ── which model does what ───────────────────────────────────────────────


def test_parsing_uses_flash_and_analysis_uses_pro() -> None:
    from the_front_office.adapters.outbound.llm.gemini import client as mod

    assert MODEL_FLASH == "gemini-2.5-flash"
    assert MODEL_PRO == "gemini-2.5-pro"
    assert "MODEL_FLASH" in inspect.getsource(mod.GeminiClient.parse_trade_string)
    assert "MODEL_PRO" in inspect.getsource(mod.GeminiClient.start_chat)
