"""Tests for terminal rendering of structured reports."""

from the_front_office.render import render_scout_report, render_trade_verdict
from the_front_office.scout.types import MOCK_SCOUT_REPORT, Recommendation, ScoutReport
from the_front_office.trade.types import MOCK_TRADE_VERDICT


def _rec(**overrides: object) -> Recommendation:
    base: dict[str, object] = {
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
    base.update(overrides)
    return Recommendation(**base)  # type: ignore[arg-type]


def test_scout_report_surfaces_every_field() -> None:
    out = render_scout_report(MOCK_SCOUT_REPORT)
    assert "MATCHUP INSIGHT" in out
    assert "TOP TARGETS" in out
    assert "FINAL STRATEGY" in out
    for rec in MOCK_SCOUT_REPORT.targets:
        assert rec.player_name in out
        assert rec.drop_player in out


def test_recommendations_are_numbered_in_order() -> None:
    out = render_scout_report(MOCK_SCOUT_REPORT)
    assert out.index("1. ADD") < out.index("2. ADD") < out.index("3. ADD")


def test_monitor_entries_render_without_a_drop() -> None:
    """With 0 adds left the model returns MONITOR entries and no drop target."""
    report = ScoutReport(
        matchup_insight="No adds left.",
        close_categories=["BLK"],
        targets=[_rec(action="MONITOR", drop_player="", drop_justification="")],
        final_strategy="Hold.",
    )
    out = render_scout_report(report)
    assert "MONITOR Test Player" in out
    assert "DROP" not in out


def test_unknown_schedule_is_stated_not_shown_as_zero() -> None:
    report = ScoutReport(
        matchup_insight="x", close_categories=[], targets=[_rec(games_remaining=0)], final_strategy="y"
    )
    out = render_scout_report(report)
    assert "schedule unknown" in out
    assert "0G left" not in out


def test_empty_target_list_is_stated_explicitly() -> None:
    report = ScoutReport(matchup_insight="x", close_categories=[], targets=[], final_strategy="y")
    assert "(none returned)" in render_scout_report(report)


def test_long_prose_is_wrapped_not_truncated() -> None:
    long_text = "word " * 200
    report = ScoutReport(matchup_insight=long_text, close_categories=[], targets=[], final_strategy="y")
    out = render_scout_report(report)
    assert max(len(line) for line in out.splitlines()) <= 80
    assert out.count("word") == 200  # nothing dropped


def test_trade_verdict_surfaces_every_field() -> None:
    out = render_trade_verdict(MOCK_TRADE_VERDICT)
    for heading in ("VERDICT:", "IMPACT", "SCHEDULE", "SHUTDOWN RISK", "STRATEGY"):
        assert heading in out
    assert MOCK_TRADE_VERDICT.verdict in out
    for cat in MOCK_TRADE_VERDICT.categories_gained:
        assert cat in out


def test_empty_category_lists_render_as_a_dash() -> None:
    from the_front_office.trade.types import TradeVerdict

    v = TradeVerdict(
        verdict="REJECT",
        verdict_detail="d",
        categories_gained=[],
        categories_lost=[],
        impact="i",
        schedule_note="s",
        shutdown_risk="r",
        strategy="st",
    )
    out = render_trade_verdict(v)
    assert "Gained: —" in out
    assert "Lost:   —" in out
