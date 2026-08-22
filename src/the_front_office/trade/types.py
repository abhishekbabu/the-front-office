from dataclasses import dataclass, field


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
