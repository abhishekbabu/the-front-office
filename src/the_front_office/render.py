"""Terminal rendering for structured reports.

The engines return validated models; this module is the only place that turns
them into text. Keeping it separate from main.py means the Streamlit UI renders
the same models its own way without inheriting terminal formatting.
"""

from the_front_office.scout.types import Recommendation, ScoutReport
from the_front_office.trade.types import TradeVerdict

_INDENT = "  "


def _wrap(text: str, width: int = 76, indent: str = _INDENT) -> str:
    """Wrap prose to `width`, prefixing every line with `indent`."""
    import textwrap

    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def _render_recommendation(rec: Recommendation, number: int) -> str:
    games = f"{rec.games_remaining}G left" if rec.games_remaining else "schedule unknown"
    cats = ", ".join(rec.categories_helped) or "—"

    lines = [
        f"{_INDENT}{number}. {rec.action} {rec.player_name} ({rec.position}, {rec.nba_team}) — {games}",
        f"{_INDENT}   Targets: {cats}",
        _wrap(rec.reasoning, indent=_INDENT + "   "),
    ]
    if rec.drop_player:
        lines.append(f"{_INDENT}   DROP {rec.drop_player}")
        lines.append(_wrap(rec.drop_justification, indent=_INDENT + "   "))
    return "\n".join(lines)


def render_scout_report(report: ScoutReport) -> str:
    """Render a scout report for the terminal."""
    close = ", ".join(report.close_categories) or "none identified"
    parts = [
        f"{_INDENT}MATCHUP INSIGHT",
        _wrap(report.matchup_insight),
        "",
        f"{_INDENT}Close categories: {close}",
        "",
        f"{_INDENT}TOP TARGETS",
    ]
    if report.targets:
        parts.extend(_render_recommendation(r, i) for i, r in enumerate(report.targets, 1))
    else:
        parts.append(f"{_INDENT}   (none returned)")
    parts.extend(["", f"{_INDENT}FINAL STRATEGY", _wrap(report.final_strategy)])
    return "\n".join(parts)


def render_trade_verdict(verdict: TradeVerdict) -> str:
    """Render a trade verdict for the terminal."""
    gained = ", ".join(verdict.categories_gained) or "—"
    lost = ", ".join(verdict.categories_lost) or "—"
    return "\n".join(
        [
            f"{_INDENT}VERDICT: {verdict.verdict}",
            _wrap(verdict.verdict_detail),
            "",
            f"{_INDENT}Gained: {gained}",
            f"{_INDENT}Lost:   {lost}",
            "",
            f"{_INDENT}IMPACT",
            _wrap(verdict.impact),
            "",
            f"{_INDENT}SCHEDULE",
            _wrap(verdict.schedule_note),
            "",
            f"{_INDENT}SHUTDOWN RISK",
            _wrap(verdict.shutdown_risk),
            "",
            f"{_INDENT}STRATEGY",
            _wrap(verdict.strategy),
        ]
    )
