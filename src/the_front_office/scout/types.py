"""Structured scout report returned by the AI.

The prompt used to ask for markdown and the CLI printed it verbatim, so nothing
could assert on it, render it differently, or check it against league rules.
These models are handed to Gemini as a response schema, so the shape is the
model's contract rather than a formatting request it may quietly ignore.
"""

from dataclasses import dataclass, field
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


@dataclass
class ScoutContext:
    """The generated prompt plus the parts it was assembled from.

    Keeping the parts lets the follow-up chat be seeded with a briefing rather
    than the whole prompt. The free-agent block is over half the prompt by
    volume, and a follow-up almost always asks about the three recommendations,
    not the twenty-seven players that were passed over.
    """

    prompt: str
    matchup_context: str = ""
    trans_context: str = ""
    schedule_context: str = ""
    roster_lines: dict[str, str] = field(default_factory=dict)
    free_agent_lines: dict[str, str] = field(default_factory=dict)

    def briefing(self, report: "ScoutReport") -> str:
        """A compact context for follow-up questions about `report`.

        Carries the matchup, budget, schedule and full roster — everything a
        "why that drop?" needs — plus only the free agents actually recommended.
        Says so explicitly, so the model declines rather than inventing numbers
        for a player it can no longer see.
        """
        named = {t.player_name for t in report.targets}
        kept = [line for name, line in self.free_agent_lines.items() if name in named]

        sections = [
            "This is a condensed briefing on a scout report you just produced.",
            self.matchup_context.strip(),
            self.trans_context.strip(),
            self.schedule_context.strip(),
            "CURRENT ROSTER:\n" + "".join(self.roster_lines.values()).strip(),
            "RECOMMENDED FREE AGENTS:\n" + ("".join(kept).strip() or "(none)"),
            (
                "NOTE: the full free-agent list is not included here. If asked about a "
                "player not shown above, say you would need to re-run the report rather "
                "than estimating their numbers."
            ),
        ]
        return "\n\n".join(s for s in sections if s)
