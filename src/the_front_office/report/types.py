"""Sport-agnostic report types.

Basketball, football and FPL differ in almost every detail — categories vs
points, adds vs FAAB vs transfer budget, matchups vs league rank — but a scout
report has the same shape in all three: read the situation, propose a ranked set
of moves, summarise the plan. These models capture that shape so one renderer,
one chat-seeding path and one UI serve every sport.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

MoveAction = Literal[
    "ADD",  # claim from the waiver wire / free agency
    "DROP",  # cut without a paired add
    "START",  # move into the starting lineup
    "BENCH",  # move out of the starting lineup
    "TRANSFER",  # FPL-style swap, paired with `replaces`
    "CAPTAIN",  # FPL captaincy
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


class TradeVerdict(BaseModel):
    """Evaluation of a proposed trade, in any sport.

    The NBA-specific spellings are gone: `categories_gained` became `gains`
    (categories in a 9-cat league, "RB depth" in football, "attacking returns"
    in FPL), and `shutdown_risk` — a basketball concept about tanking teams
    resting stars — became `risk`, which also covers an injury designation or a
    rotation-prone FPL asset.
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
    squad_lines: dict[str, str] = field(default_factory=dict)
    candidate_lines: dict[str, str] = field(default_factory=dict)

    def briefing(self, report: ScoutReport) -> str:
        """A compact context for follow-up questions about `report`.

        Carries the situation, constraints and full squad — what a "why that
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
            "CURRENT SQUAD:\n" + "".join(self.squad_lines.values()).strip(),
            "PLAYERS NAMED IN THE REPORT:\n" + ("".join(kept).strip() or "(none)"),
            (
                "NOTE: the full candidate pool is not included here. If asked about a player "
                "not shown above, say you would need to re-run the report rather than "
                "estimating their numbers."
            ),
        ]
        return "\n\n".join(s for s in sections if s)
