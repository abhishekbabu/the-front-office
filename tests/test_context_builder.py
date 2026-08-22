"""Tests for PlayerContextBuilder's stat formatting."""

from the_front_office.clients.nba.types import NineCatStats, PlayerStats
from the_front_office.services.context_builder import PlayerContextBuilder


def _stats(**overrides: float) -> NineCatStats:
    base: dict[str, float] = {
        "PTS": 20.0,
        "REB": 10.0,
        "AST": 5.0,
        "STL": 1.0,
        "BLK": 2.0,
        "TOV": 3.0,
        "FG3M": 2.0,
        "FG_PCT": 0.523,
        "FT_PCT": 0.781,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def _builder() -> PlayerContextBuilder:
    return PlayerContextBuilder(nba_client=None)  # type: ignore[arg-type]


def test_empty_stats_reports_unavailable() -> None:
    assert _builder()._format_stats(PlayerStats()) == "No stats available"


def test_percentages_render_as_percentages_not_decimals() -> None:
    """The AI prompt is easier to reason over in FG52.3% form than FG0.523."""
    out = _builder()._format_stats(PlayerStats(last_5=_stats()))
    assert "FG52.3%" in out
    assert "FT78.1%" in out


def test_all_present_windows_are_included_in_order() -> None:
    out = _builder()._format_stats(
        PlayerStats(last_5=_stats(PTS=1.0), last_10=_stats(PTS=2.0), last_15=_stats(PTS=3.0))
    )
    assert out.index("L5:") < out.index("L10:") < out.index("L15:")
    assert out.count("|") == 2


def test_missing_windows_are_skipped() -> None:
    """A player with fewer than 10 games has only last_5 populated."""
    out = _builder()._format_stats(PlayerStats(last_5=_stats()))
    assert "L5:" in out
    assert "L10:" not in out
    assert "|" not in out


def test_counting_stats_are_labelled() -> None:
    out = _builder()._format_stats(PlayerStats(last_5=_stats()))
    for fragment in ("20.0p", "10.0r", "5.0a", "1.0s", "2.0b", "3.0to", "2.03pm"):
        assert fragment in out
