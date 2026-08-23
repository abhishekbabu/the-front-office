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


Tone = Literal["neutral", "good", "warning"]
"""Whether a figure should pull the eye. Named so a provider computing one can
say so in its signature rather than returning a bare string."""


class Stat(BaseModel):
    """One headline figure: where the team stands before any reading happens.

    Computed by the provider from league state, never by the model — these are
    exact and a hallucinated rank or bank balance would be worse than none.
    """

    label: str = Field(description="Short name in the league's own vocabulary: 'Bank', 'Free transfers'.")
    value: str = Field(description="Already formatted for display, with its unit: '£2.5m', '340,112', '0-0'.")
    tone: Tone = Field(
        default="neutral",
        description=(
            "Whether this figure should pull the eye. 'warning' for something costing points now — "
            "points left on the bench, an expiring allowance — and 'good' for headroom worth spending."
        ),
    )


class Spot(BaseModel):
    """One place in a lineup, or one player on a bench.

    Sport-neutral on purpose: a slot is "FLEX" in football and "" in FPL, where
    a formation has positions but not named places, and both render the same.
    """

    player_id: str = Field(default="", description="Identifier this sport uses, for opening the player.")
    slot: str = Field(default="", description="Named place in the lineup, where the sport has them.")
    player: str
    detail: str = Field(description="Position, club and opponent, as that sport words it.")
    value: str = Field(description="The forward-looking number, with its unit.")
    tone: Tone = "neutral"


class Side(BaseModel):
    """One team in a matchup — yours, or the one you are playing."""

    name: str
    detail: str = Field(default="", description="Record, manager, or however the league identifies a team.")
    points: str = Field(default="", description="What they have scored, or are projected to.")
    lineup: list[Spot] = Field(default_factory=list)
    bench: list[Spot] = Field(default_factory=list)


class PlayerCard(BaseModel):
    """A player as a row in a roster table.

    `columns` is the sport's own vocabulary — FPL sends Price and xPts, football
    sends Slot — so a client renders whatever keys arrive rather than being
    taught each sport. What sits beside it is what a table needs and a column
    should not be: an identifier to open, and whether the row wants attention.
    """

    player_id: str
    columns: dict[str, str]
    tone: Tone = "neutral"


class StatGroup(BaseModel):
    """A handful of related figures under a heading.

    Twenty numbers in one list is a wall; the same twenty under "This week",
    "Season" and "Set pieces" can be read without looking for anything.
    """

    title: str
    stats: list[Stat] = Field(default_factory=list)


class StatRow(BaseModel):
    """One measure, across every column of a table."""

    label: str
    values: list[str] = Field(
        description=(
            "One per column, in the same order. 'N/A' where that column has no answer — "
            "distinct from '0', which is an answer."
        )
    )
    tone: Tone = "neutral"


class StatTable(BaseModel):
    """The same measures across several periods, so they can be read across.

    A stack of per-season groups makes you hold last year's goals in your head
    while you scroll to this year's. A table puts them on one line, which is
    the whole reason anybody looks at more than one season.
    """

    title: str
    columns: list[str] = Field(description="Period labels, newest first: ['2026/27', '2025/26', '2024/25'].")
    rows: list[StatRow] = Field(default_factory=list)


class PlayerDetail(BaseModel):
    """Everything worth knowing about one player, on demand.

    Fetched when someone asks rather than carried by every row: the interesting
    numbers differ per sport and there are a dozen of them, which is a table
    nobody can read attached to a payload nobody needs.
    """

    player_id: str
    name: str
    position: str
    team: str
    headline: str = Field(
        default="",
        description=(
            "The one figure this player is judged on, bare — '22.3', not '22.3 proj pts'. "
            "Empty when there is none, which is not the same as zero."
        ),
    )
    headline_label: str = Field(
        default="",
        description=(
            "What that figure is: 'projected this week', 'xPts this week'. When `headline` is "
            "empty this stands alone and says why there is no figure, so it reads as a sentence "
            "rather than as a number that failed to arrive."
        ),
    )
    note: str = Field(default="", description="Injury or availability news, in the platform's words.")
    image_url: str = Field(
        default="",
        description=(
            "Portrait on the platform's own CDN, or empty where that sport has none. "
            "A URL rather than bytes: it is the client that has a cache for it."
        ),
    )
    tone: Tone = "neutral"
    groups: list[StatGroup] = Field(default_factory=list)
    tables: list[StatTable] = Field(
        default_factory=list,
        description="Comparisons across periods, which a list of groups cannot show.",
    )


class Swap(BaseModel):
    """A change the numbers already imply, before anyone has judged them."""

    start: str
    out: str = Field(default="", description="Who comes out. Empty when a place was unfilled.")
    gain: str


class Summary(BaseModel):
    """Where a team stands, with no analysis in it.

    Everything here is read or computed from league state, so it is available
    the moment a page opens rather than after a model has answered.
    """

    headline: list[Stat] = Field(default_factory=list)
    mine: Side | None = None
    opponent: Side | None = None
    """Absent when the week has no fixture, which is not a nil-nil scoreline."""

    swaps: list[Swap] = Field(default_factory=list)
    """Changes the projections imply. Exact, and the report's job is to endorse
    or overrule them rather than to find them."""

    fixtures: list[Stat] = Field(default_factory=list)
    """The real-world matches behind the week, one per club in play."""

    window: str = Field(
        default="",
        description=(
            "When this week actually is, already formatted — 'Week 1 · Sep 11-15', "
            "'GW 2 · deadline Sat 22 Aug 10:30'. A week with no dates on it is a number."
        ),
    )


class ScheduleRow(BaseModel):
    """One week of your own season, played or still to come."""

    label: str = Field(description="What the league calls the week: 'Week 3', 'GW 12'.")
    date: str = Field(default="", description="When it is played, in the reader's words: 'Sep 14', 'Sat 13 Sep'.")
    opponent: str = Field(default="", description="Who you play. Empty on a bye, which is not an opponent named 'bye'.")
    detail: str = Field(default="", description="Their record, or however the league identifies them.")
    result: str = Field(default="", description="The score once it is played, and nothing before that.")
    tone: Tone = "neutral"
    is_current: bool = False
    """The week in progress, so a long table can say where you are in it."""


class TeamRef(BaseModel):
    """One team in the league, addressable so its roster can be opened."""

    team_id: str = Field(description="Identifier this platform uses for a team, roster or entry.")
    name: str
    detail: str = Field(default="", description="Record, manager, or however the league identifies them.")
    is_mine: bool = False


class StandingRow(BaseModel):
    """One team in the league table."""

    rank: int
    name: str
    detail: str = Field(default="", description="Manager, or however the league identifies the entry.")
    record: str = Field(default="", description="In the league's own terms: '3-1', '2W 1D 1L'.")
    points: str = Field(default="", description="What the table is actually sorted on.")
    team_id: str = Field(
        default="",
        description="Addresses this team's roster. Empty where the platform cannot serve one.",
    )
    is_mine: bool = False
    """Yours, so a fourteen-team table does not have to be read to find it."""


class Match(BaseModel):
    """One real-world game behind a fantasy week.

    Distinct from a fantasy fixture: this is two actual clubs, on a date, and
    it is what a projection is a projection *about*.
    """

    label: str = Field(default="", description="When it kicks off, already formatted.")
    home: str
    away: str
    detail: str = Field(default="", description="Difficulty, status, or whatever that sport reads off a fixture.")
    tone: Tone = "neutral"


class ActivityRow(BaseModel):
    """One thing somebody in the league did."""

    when: str = Field(default="", description="Already formatted; a raw epoch is not a date.")
    who: str = Field(default="", description="The manager, not the roster id.")
    what: str = Field(description="Add, drop, trade, waiver — in the platform's own vocabulary.")
    detail: str = Field(default="", description="The players involved.")
    tone: Tone = "neutral"


class LeagueSchedule(BaseModel):
    """The league beyond this week: where the season goes, and where you sit.

    Every section is optional because the platforms genuinely differ — a
    classic FPL league has a table and no head-to-head season, and FPL has no
    transaction feed at all. An empty section renders as nothing rather than as
    an empty promise.
    """

    season: list[ScheduleRow] = Field(default_factory=list)
    standings: list[StandingRow] = Field(default_factory=list)
    matches: list[Match] = Field(default_factory=list)
    activity: list[ActivityRow] = Field(default_factory=list)


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
