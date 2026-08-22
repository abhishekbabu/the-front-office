"""Tests for TradeEvaluator's player resolution."""

from types import SimpleNamespace

import pytest

from the_front_office.exceptions import PlayerNotFoundError
from the_front_office.trade.engine import TradeEvaluator


class _FakeYahoo:
    """Stands in for YahooFantasyClient.search_players."""

    def __init__(self, results: dict[str, list[object]]) -> None:
        self.results = results
        self.queries: list[str] = []

    def search_players(self, query: str) -> list[object]:
        self.queries.append(query)
        return self.results.get(query, [])


def _player(name: str) -> object:
    return SimpleNamespace(name=SimpleNamespace(full=name))


def _evaluator(yahoo: _FakeYahoo) -> TradeEvaluator:
    e = TradeEvaluator.__new__(TradeEvaluator)
    e.yahoo = yahoo  # type: ignore[assignment]
    return e


def test_resolves_an_exact_match() -> None:
    yahoo = _FakeYahoo({"LeBron James": [_player("LeBron James")]})
    resolved = _evaluator(yahoo)._resolve_players(["LeBron James"])
    assert len(resolved) == 1
    assert yahoo.queries == ["LeBron James"]


def test_falls_back_to_the_last_name() -> None:
    """'Lebron James' (wrong casing) misses, but 'James' should still find him."""
    yahoo = _FakeYahoo({"James": [_player("LeBron James")]})
    resolved = _evaluator(yahoo)._resolve_players(["Lebron James"])
    assert len(resolved) == 1
    assert yahoo.queries == ["Lebron James", "James"]


def test_unresolved_name_raises_rather_than_being_dropped() -> None:
    """Regression: a typo used to be logged and silently omitted, so the AI
    evaluated a different trade than the one the user typed."""
    yahoo = _FakeYahoo({"LeBron James": [_player("LeBron James")]})
    with pytest.raises(PlayerNotFoundError) as excinfo:
        _evaluator(yahoo)._resolve_players(["LeBron James", "Notarealplayer"])
    assert excinfo.value.names == ["Notarealplayer"]


def test_every_unresolved_name_is_reported_at_once() -> None:
    yahoo = _FakeYahoo({})
    with pytest.raises(PlayerNotFoundError) as excinfo:
        _evaluator(yahoo)._resolve_players(["Ghost One", "Ghost Two"])
    assert excinfo.value.names == ["Ghost One", "Ghost Two"]


def test_surrounding_whitespace_is_stripped() -> None:
    yahoo = _FakeYahoo({"LeBron James": [_player("LeBron James")]})
    assert len(_evaluator(yahoo)._resolve_players(["  LeBron James  "])) == 1


def test_ambiguous_match_takes_the_first_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    yahoo = _FakeYahoo({"Williams": [_player("Jalen Williams"), _player("Jaylen Williams")]})
    with caplog.at_level("WARNING"):
        resolved = _evaluator(yahoo)._resolve_players(["Williams"])
    assert len(resolved) == 1
    assert "2 matches" in caplog.text
