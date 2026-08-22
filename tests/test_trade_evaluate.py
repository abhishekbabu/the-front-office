"""Tests for the full TradeEvaluator.evaluate flow."""

from typing import Any

import pytest
from conftest import FakeAI, FakeNBA, FakeYahoo, make_player

from the_front_office.exceptions import PlayerNotFoundError, TradeParseError
from the_front_office.trade.engine import TradeEvaluator
from the_front_office.trade.types import MOCK_TRADE_VERDICT, TradeProposal, TradeVerdict


def _evaluator(yahoo: FakeYahoo, ai: FakeAI | None = None) -> TradeEvaluator:
    return TradeEvaluator(league=None, ai=ai or FakeAI(), nba=FakeNBA(), yahoo=yahoo)  # type: ignore[arg-type]


def _yahoo_with(*names: str) -> FakeYahoo:
    return FakeYahoo(search_results={n: [make_player(n)] for n in names})


def test_returns_a_validated_verdict_and_an_open_chat() -> None:
    ai = FakeAI()
    yahoo = _yahoo_with("LeBron James", "Jayson Tatum")
    verdict, chat = _evaluator(yahoo, ai=ai).evaluate("Give LeBron, Get Tatum")
    assert isinstance(verdict, TradeVerdict)
    assert verdict == MOCK_TRADE_VERDICT
    assert chat is ai.chat


def test_google_search_is_enabled_for_live_injury_news() -> None:
    ai = FakeAI()
    _evaluator(_yahoo_with("LeBron James", "Jayson Tatum"), ai=ai).evaluate("x")
    assert ai.search_enabled is True


def test_search_grounded_prose_is_structured_in_a_second_pass() -> None:
    """A response schema cannot accompany a tool, so prose is converted after."""
    ai = FakeAI(prose="[FAKE] verdict prose")
    _evaluator(_yahoo_with("LeBron James", "Jayson Tatum"), ai=ai).evaluate("x")
    assert ai.structured_text == ["[FAKE] follow-up answer"]


def test_unparseable_trade_raises_before_any_lookup() -> None:
    ai = FakeAI(proposal=TradeProposal())
    yahoo = _yahoo_with("LeBron James")
    with pytest.raises(TradeParseError):
        _evaluator(yahoo, ai=ai).evaluate("gibberish")
    assert yahoo.searches == []


def test_unresolvable_player_raises_before_the_expensive_call() -> None:
    ai = FakeAI(proposal=TradeProposal(giving=["Ghost Player"], receiving=["Jayson Tatum"]))
    with pytest.raises(PlayerNotFoundError) as excinfo:
        _evaluator(_yahoo_with("Jayson Tatum"), ai=ai).evaluate("x")
    assert excinfo.value.names == ["Ghost Player"]
    assert ai.structured_text == []


def test_prompt_includes_both_sides_and_the_current_roster() -> None:
    ai = FakeAI()
    yahoo = _yahoo_with("LeBron James", "Jayson Tatum")
    yahoo.roster = [make_player("Existing Starter")]
    _evaluator(yahoo, ai=ai).evaluate("x")
    prompt = ai.chat.sent[0]
    assert "LeBron James" in prompt
    assert "Jayson Tatum" in prompt
    assert "Existing Starter" in prompt  # roster awareness rule needs this


def test_roster_failure_degrades_instead_of_blocking_the_evaluation() -> None:
    """Roster context is enrichment; losing it must not lose the answer."""

    class BadRoster(FakeYahoo):
        def get_matchup_dates(self, my_team: Any) -> tuple[str, str]:
            raise RuntimeError("yahoo hiccup")

    yahoo = BadRoster(search_results={n: [make_player(n)] for n in ("LeBron James", "Jayson Tatum")})
    ai = FakeAI()
    verdict, _ = _evaluator(yahoo, ai=ai).evaluate("x")
    assert verdict == MOCK_TRADE_VERDICT
    assert "Roster data unavailable" in ai.chat.sent[0]
