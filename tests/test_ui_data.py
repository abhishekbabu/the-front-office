"""Tests for the UI data layer.

app.py is a Streamlit rendering shell, but everything it computes lives here and
is testable without a Streamlit runtime.
"""

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import make_player

from the_front_office.ui import data

# ── season_year ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 10, 20), 2026),  # opening night
        (datetime(2026, 12, 31), 2026),
        (datetime(2027, 1, 2), 2026),  # January still belongs to the prior season
        (datetime(2027, 4, 15), 2026),  # playoffs
        (datetime(2026, 9, 1), 2026),  # September boundary, inclusive
        (datetime(2026, 8, 31), 2025),  # the day before
    ],
)
def test_season_year_rolls_over_in_september(when: datetime, expected: int) -> None:
    assert data.season_year(when) == expected


# ── roster_rows ─────────────────────────────────────────────────────────


def _team(players: list[Any]) -> Any:
    return SimpleNamespace(name="My Team", players=lambda: players)


def test_roster_rows_carry_the_display_fields() -> None:
    rows = data.roster_rows(_team([make_player("A B", position="PF,C", team="LAL")]))
    assert rows == [{"Player": "A B", "Pos": "PF,C", "Team": "LAL", "Slot": "", "Status": ""}]


def test_roster_rows_surface_slot_and_status_when_present() -> None:
    player = make_player("Hurt Guy", status="O", selected_position="IL")
    rows = data.roster_rows(_team([player]))
    assert rows[0]["Slot"] == "IL"
    assert rows[0]["Status"] == "O"


def test_empty_roster_yields_no_rows() -> None:
    assert data.roster_rows(_team([])) == []


# ── matchup_rows ────────────────────────────────────────────────────────

CONTEXT = """
CURRENT MATCHUP: Playing against Their Team
MATCHUP SCORE: You 5 - 4 Opponent

CATEGORY BREAKDOWN (Us vs Opponent):
- FG%: .482 vs .461
- BLK: 12 vs 17
- TO: 41 vs 38
OPPONENT KEY PLAYERS: Star Player (PG)
"""


def test_category_rows_are_parsed_from_the_prompt_context() -> None:
    """Reuses the context already built for the AI rather than re-querying Yahoo."""
    rows = data.matchup_rows(CONTEXT)
    assert rows == [
        {"Category": "FG%", "You": ".482", "Opponent": ".461"},
        {"Category": "BLK", "You": "12", "Opponent": "17"},
        {"Category": "TO", "You": "41", "Opponent": "38"},
    ]


def test_non_category_lines_are_ignored() -> None:
    rows = data.matchup_rows(CONTEXT)
    assert all(r["Category"] not in ("CURRENT MATCHUP", "OPPONENT KEY PLAYERS") for r in rows)


def test_empty_context_yields_no_rows() -> None:
    """get_matchup_context returns "" when there is no matchup in progress."""
    assert data.matchup_rows("") == []


def test_context_without_a_breakdown_yields_no_rows() -> None:
    assert data.matchup_rows("CURRENT MATCHUP: Playing against Their Team") == []
