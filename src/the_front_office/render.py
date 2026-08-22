"""Terminal rendering for scout reports.

The engines return validated models; this module is the only place that turns
them into text. Keeping it separate from main.py means the Streamlit UI renders
the same models its own way, and one renderer serves every sport.
"""

import textwrap

from the_front_office.report.types import Move, ScoutReport
from the_front_office.trade.types import TradeVerdict

_INDENT = "  "


def _wrap(text: str, width: int = 76, indent: str = _INDENT) -> str:
    """Wrap prose to `width`, prefixing every line with `indent`."""
    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def _render_move(move: Move, number: int) -> str:
    lines = [
        f"{_INDENT}{number}. {move.action} {move.player} ({move.position}, {move.team}) — {move.metric}",
        _wrap(move.rationale, indent=_INDENT + "   "),
    ]
    if move.replaces:
        verb = {"ADD": "DROP", "START": "BENCH", "TRANSFER": "OUT"}.get(move.action, "REPLACES")
        lines.append(f"{_INDENT}   {verb} {move.replaces}")
        if move.replaces_rationale:
            lines.append(_wrap(move.replaces_rationale, indent=_INDENT + "   "))
    return "\n".join(lines)


def render_scout_report(report: ScoutReport) -> str:
    """Render a scout report for the terminal."""
    focus = ", ".join(report.focus) or "none identified"
    parts = [
        f"{_INDENT}SITUATION",
        _wrap(report.situation),
        "",
        f"{_INDENT}Focus: {focus}",
        "",
        f"{_INDENT}MOVES",
    ]
    if report.moves:
        parts.extend(_render_move(m, i) for i, m in enumerate(report.moves, 1))
    else:
        parts.append(f"{_INDENT}   (none returned)")
    parts.extend(["", f"{_INDENT}STRATEGY", _wrap(report.strategy)])
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
