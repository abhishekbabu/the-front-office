"""Canned reports for `--mock`, so the report path runs without credentials.

One per sport: a mock basketball report returned for `/football --mock` would
exercise the rendering path but tell you nothing about whether the football
prompt produces a sensible shape.
"""

from the_front_office.domain.models import Move, ScoutReport, TradeVerdict

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


MOCK_TRADE_VERDICT = TradeVerdict(
    verdict="ACCEPT",
    verdict_detail="[MOCK] The incoming side is the better rest-of-season value.",
    gains=["REB", "BLK"],
    losses=["AST", "FT%"],
    impact="[MOCK] Net gain in REB and BLK on recent form, roughly neutral scoring, slight FT% dip.",
    schedule="[MOCK] Incoming player has one extra game in each playoff week.",
    risk="[MOCK] Neither incoming player is on a tanking team or carrying a designation.",
    strategy="[MOCK] Accept, then stream a guard to cover the AST dip.",
)


MOCK_FOOTBALL_REPORT = ScoutReport(
    situation=(
        "[MOCK] Projected to win by 6. The margin rests on the flex slot, where the "
        "bench currently holds the higher projection."
    ),
    focus=["FLEX", "TE bye", "RB2 injury risk"],
    moves=[
        Move(
            action="START",
            player="Mock Running Back",
            position="RB",
            team="BUF",
            metric="16.7 proj pts, +4.2 over the current starter",
            rationale="[MOCK] Clear volume lead and a bottom-five run defence opposite him.",
            replaces="Mock Bench Back",
            replaces_rationale="[MOCK] Splitting carries and facing the league's best front.",
        ),
        Move(
            action="ADD",
            player="Mock Waiver Receiver",
            position="WR",
            team="NYJ",
            metric="12.4 proj pts",
            rationale="[MOCK] Promoted to the slot with the starter out; target share should spike.",
            replaces="Mock Backup Kicker",
            replaces_rationale="[MOCK] Streaming a kicker is cheaper than rostering two.",
        ),
    ],
    strategy="[MOCK] Fix the flex, then stream the open roster spot for upside.",
)

MOCK_REPORTS: dict[str, ScoutReport] = {
    "nba": MOCK_SCOUT_REPORT,
    "nfl": MOCK_FOOTBALL_REPORT,
}


def mock_report_for(sport: str) -> ScoutReport:
    """The canned report for a sport, falling back to the basketball one."""
    return MOCK_REPORTS.get(sport, MOCK_SCOUT_REPORT)
