"""Canned reports for `--mock`, so the report path runs without credentials."""

from the_front_office.report.types import Move, ScoutReport

MOCK_SCOUT_REPORT = ScoutReport(
    situation=(
        "[MOCK] Positioned for a 6-3 win. BLK is within 4 and FG% is a slim lead worth "
        "protecting; PTS is lost by a landslide and not worth chasing."
    ),
    focus=["BLK", "FG%", "REB"],
    moves=[
        Move(
            action="ADD",
            player="Mock Player One",
            position="PF,C",
            team="LAL",
            metric="4 games left",
            rationale="[MOCK] Elite rebounding across four remaining games, and blocks at volume.",
            replaces="Mock Bench Warmer",
            replaces_rationale="[MOCK] Two games left and no category he wins.",
        ),
        Move(
            action="ADD",
            player="Mock Player Two",
            position="C",
            team="BOS",
            metric="3 games left",
            rationale="[MOCK] Efficient interior scoring protects the FG% lead.",
            replaces="Mock Injured Reserve",
            replaces_rationale="[MOCK] Out indefinitely and occupying an active slot.",
        ),
        Move(
            action="ADD",
            player="Mock Player Three",
            position="SG",
            team="GSW",
            metric="4 games left",
            rationale="[MOCK] High-volume shooter to secure the 3PTM margin.",
            replaces="Mock Inconsistent Guard",
            replaces_rationale="[MOCK] Poor recent form, redundant with the current backcourt.",
        ),
    ],
    strategy="[MOCK] Add multi-category bigs to flip BLK without surrendering FG%.",
)
