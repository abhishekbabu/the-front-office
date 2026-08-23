"""Sport-agnostic report types.

Sports differ in almost every detail — categories versus points, adds versus a
transfer budget, head-to-head versus league rank — but a report has the same
shape in each: read the situation, propose a ranked set of moves, summarize the
plan. One renderer, one chat-seeding path and one UI serve them all.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

MoveAction = Literal[
    "ADD",  # claim from the waiver wire / free agency
    "DROP",  # cut without a paired add
    "START",  # move into the starting lineup
    "BENCH",  # move out of the starting lineup
    "TRANSFER",  # swap one player for another, paired with `replaces`
    "CAPTAIN",  # nominate as captain
    "MONITOR",  # no action possible now; watch for later
]


class Move(BaseModel):
    """One recommended action on one player."""

    action: MoveAction = Field(description="What to do with this player.")
    player: str = Field(description="Full player name as the platform spells it.")
    position: str = Field(description="Position or eligible slots, e.g. 'RB' or 'PG,SG'.")
    team: str = Field(description="Real-world team abbreviation, e.g. 'BUF' or 'LAL'.")
    metric: str = Field(
        description=(
            "The number that justifies this move, with its unit — '22.3 proj pts', '4 games left', '£8.5m, 6.2 xPts'."
        )
    )
    rationale: str = Field(description="Why this move helps. Tactical and specific, no filler.")
    replaces: str = Field(
        default="",
        description="Counterpart player being dropped, benched or transferred out. Empty when there is none.",
    )
    replaces_rationale: str = Field(default="", description="Why that counterpart is the right one to move.")


class Stat(BaseModel):
    """One headline figure: where the team stands before any reading happens.

    Computed by the provider from league state, never by the model — these are
    exact and a hallucinated rank or bank balance would be worse than none.
    """

    label: str = Field(description="Short name in the league's own vocabulary: 'Bank', 'Free transfers'.")
    value: str = Field(description="Already formatted for display, with its unit: '£2.5m', '340,112', '0-0'.")
    tone: Literal["neutral", "good", "warning"] = Field(
        default="neutral",
        description=(
            "Whether this figure should pull the eye. 'warning' for something costing points now — "
            "points left on the bench, an expiring allowance — and 'good' for headroom worth spending."
        ),
    )


class ScoutReport(BaseModel):
    """A scouting report for any sport."""

    situation: str = Field(description="Where the team stands: the matchup, the run of fixtures, the league position.")
    focus: list[str] = Field(
        description=(
            "What this week turns on — close categories, thin positions, players on a bye. "
            "Short labels, e.g. ['BLK', 'FG%'] or ['RB depth', 'QB bye']."
        )
    )
    moves: list[Move] = Field(description="Recommended moves, most valuable first.")
    strategy: str = Field(description="One-sentence summary of the plan.")

    headline: list[Stat] = Field(
        default_factory=list,
        description=(
            "LEAVE THIS EMPTY. The application overwrites it with figures read straight from the "
            "platform, so anything put here is discarded."
        ),
    )


class TradeVerdict(BaseModel):
    """Evaluation of a proposed trade, in any sport.

    Field names are in whatever currency the league scores in: `gains` holds
    categories in a 9-cat league and position depth in a points league.
    """

    verdict: Literal["ACCEPT", "REJECT", "COUNTER"] = Field(description="The recommendation.")
    verdict_detail: str = Field(description="One or two sentences justifying the verdict.")
    gains: list[str] = Field(
        description=(
            "What this trade improves. Short labels in the league's own currency — "
            "['REB', 'BLK'] for categories, ['RB depth'] for points leagues."
        )
    )
    losses: list[str] = Field(description="What this trade weakens, in the same terms.")
    impact: str = Field(description="Net change in the league's scoring terms, referencing recent form.")
    schedule: str = Field(
        description="How the fixtures or remaining games compare, especially through the playoff weeks."
    )
    risk: str = Field(
        description=(
            "Availability risk on the incoming side: shutdown on a tanking team, injury designation, or rotation risk."
        )
    )
    strategy: str = Field(description="What to do next, including any counter-offer worth making.")


@dataclass
class TradeProposal:
    """
    Represents a trade proposal parsed from natural language.
    """

    giving: list[str] = field(default_factory=list)
    receiving: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return bool(self.giving) and bool(self.receiving)


@dataclass
class SportContext:
    """A rendered prompt plus the parts it was assembled from.

    Keeping the parts lets a follow-up chat be seeded with a briefing rather
    than the whole prompt, which is resent on every turn and is dominated by the
    candidate pool — the players that were considered and passed over.
    """

    prompt: str
    situation: str = ""
    constraints: str = ""
    extra: str = ""
    roster_lines: dict[str, str] = field(default_factory=dict)
    candidate_lines: dict[str, str] = field(default_factory=dict)
    headline: list[Stat] = field(default_factory=list)
    """Exact figures for the report header, read from league state rather than written by the model."""

    def briefing(self, report: ScoutReport) -> str:
        """A compact context for follow-up questions about `report`.

        Carries the situation, constraints and full roster — what a "why that
        drop?" needs — plus only the candidates actually named. Says so, so the
        model declines rather than inventing numbers for a player it cannot see.
        """
        named = {m.player for m in report.moves} | {m.replaces for m in report.moves if m.replaces}
        kept = [line for name, line in self.candidate_lines.items() if name in named]

        sections = [
            "This is a condensed briefing on a report you just produced.",
            self.situation.strip(),
            self.constraints.strip(),
            self.extra.strip(),
            "CURRENT ROSTER:\n" + "".join(self.roster_lines.values()).strip(),
            "PLAYERS NAMED IN THE REPORT:\n" + ("".join(kept).strip() or "(none)"),
            (
                "NOTE: the full candidate pool is not included here. If asked about a player "
                "not shown above, say you would need to re-run the report rather than "
                "estimating their numbers."
            ),
        ]
        return "\n\n".join(s for s in sections if s)
