from dataclasses import dataclass, field
from typing import List


@dataclass
class TradeProposal:
    """
    Represents a trade proposal parsed from natural language.
    """
    giving: List[str] = field(default_factory=list)
    receiving: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return bool(self.giving) and bool(self.receiving)
