"""Structured scout report returned by the AI.

The prompt used to ask for markdown and the CLI printed it verbatim, so nothing
could assert on it, render it differently, or check it against league rules.
These models are handed to Gemini as a response schema, so the shape is the
model's contract rather than a formatting request it may quietly ignore.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Recommendation(BaseModel):
    """One waiver-wire move: a player to add (or monitor) and who to drop for them."""

    action: Literal["ADD", "MONITOR"] = Field(
        description="ADD when adds remain this week; MONITOR when the add budget is exhausted."
    )
    player_name: str = Field(description="Full name exactly as it appears on Yahoo.")
    position: str = Field(description="Yahoo display position, e.g. 'PG,SG'.")
    nba_team: str = Field(description="NBA team abbreviation, e.g. 'LAL'.")
    games_remaining: int = Field(description="Games left for this player's team in the matchup period. 0 if unknown.")
    categories_helped: list[str] = Field(description="Which close categories this move targets, e.g. ['BLK', 'REB'].")
    reasoning: str = Field(description="Why this player helps those categories. Tactical, no filler.")
    drop_player: str = Field(description="Roster player to drop. Empty string when action is MONITOR.")
    drop_justification: str = Field(description="Why that player is the right drop.")


class ScoutReport(BaseModel):
    """A full Morning Scout Report."""

    matchup_insight: str = Field(
        description="Category analysis focused on securing a 5-4 win: which categories are close."
    )
    close_categories: list[str] = Field(
        description="Categories within reach — winnable or at risk. Use short names like 'FG%', '3PTM'."
    )
    targets: list[Recommendation] = Field(description="Exactly three recommendations.")
    final_strategy: str = Field(description="One-sentence tactical summary.")


MOCK_SCOUT_REPORT = ScoutReport(
    matchup_insight=(
        "[MOCK] Positioned for a 6-3 win. BLK is within 4 and FG% is a slim lead worth protecting; "
        "PTS is lost by a landslide and not worth chasing."
    ),
    close_categories=["BLK", "FG%", "REB"],
    targets=[
        Recommendation(
            action="ADD",
            player_name="Mock Player One",
            position="PF,C",
            nba_team="LAL",
            games_remaining=4,
            categories_helped=["REB", "BLK"],
            reasoning="[MOCK] Elite rebounding on four remaining games, and blocks at volume.",
            drop_player="Mock Bench Warmer",
            drop_justification="[MOCK] Two games left and no category he wins.",
        ),
        Recommendation(
            action="ADD",
            player_name="Mock Player Two",
            position="C",
            nba_team="BOS",
            games_remaining=3,
            categories_helped=["BLK", "FG%"],
            reasoning="[MOCK] Efficient interior scoring protects the FG% lead.",
            drop_player="Mock Injured Reserve",
            drop_justification="[MOCK] Out indefinitely and occupying an active slot.",
        ),
        Recommendation(
            action="ADD",
            player_name="Mock Player Three",
            position="SG",
            nba_team="GSW",
            games_remaining=4,
            categories_helped=["3PTM"],
            reasoning="[MOCK] High-volume shooter to secure the 3PTM margin.",
            drop_player="Mock Inconsistent Guard",
            drop_justification="[MOCK] Poor recent form, redundant with the current backcourt.",
        ),
    ],
    final_strategy="[MOCK] Add multi-category bigs to flip BLK without surrendering FG%.",
)
