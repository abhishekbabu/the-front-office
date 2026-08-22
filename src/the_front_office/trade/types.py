from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


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


class TradeVerdict(BaseModel):
    """Structured evaluation of a proposed trade."""

    verdict: Literal["ACCEPT", "REJECT", "COUNTER"] = Field(description="The recommendation.")
    verdict_detail: str = Field(description="One or two sentences justifying the verdict.")
    categories_gained: list[str] = Field(description="Categories this trade improves, e.g. ['REB', 'BLK'].")
    categories_lost: list[str] = Field(description="Categories this trade weakens.")
    impact: str = Field(description="Net statistical change, referencing L15/L30 form.")
    schedule_note: str = Field(description="Who has more games in the fantasy playoff weeks.")
    shutdown_risk: str = Field(description="Whether any incoming player risks being shut down by a tanking team.")
    strategy: str = Field(description="What to do next, including any counter-offer worth making.")


MOCK_TRADE_VERDICT = TradeVerdict(
    verdict="ACCEPT",
    verdict_detail="[MOCK] The incoming side is the better rest-of-season value.",
    categories_gained=["REB", "BLK"],
    categories_lost=["AST", "FT%"],
    impact="[MOCK] Net gain in REB and BLK on L15 form, roughly neutral PTS, slight FT% dip.",
    schedule_note="[MOCK] Incoming player has one extra game in each playoff week.",
    shutdown_risk="[MOCK] Neither incoming player is on a tanking team.",
    strategy="[MOCK] Accept, then stream a guard to cover the AST dip.",
)
