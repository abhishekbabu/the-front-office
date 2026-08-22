"""The interfaces the core depends on.

Ports live with the code that *uses* them, not with the code that implements
them. That is what keeps the dependency arrows pointing inward: the domain names
what it needs, and the adapters satisfy it. Nothing in this package imports an
adapter.
"""

from dataclasses import dataclass
from typing import Protocol, TypedDict, TypeVar, runtime_checkable

from pydantic import BaseModel

from the_front_office.domain.models import SportContext, TradeProposal

TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(frozen=True)
class LeagueRef:
    """A league the user is in, in whatever platform the sport uses."""

    league_id: str
    name: str
    sport: str
    detail: str = ""
    """Anything worth showing beside the name — record, scoring format, team count."""


class HistoryTurn(TypedDict):
    """One turn of a seeded conversation.

    Defined here rather than in the LLM adapter because the engines construct
    these when they seed a follow-up chat, and the port has to name the same
    shape the adapter accepts.
    """

    role: str
    parts: list[str]


class ChatSession(Protocol):
    """An open conversation, for follow-up questions about a finished report."""

    def send_message(self, message: str) -> object: ...


@runtime_checkable
class AnalysisModel(Protocol):
    """The language model the engines talk to.

    Named as a capability rather than a vendor so the core never imports
    `clients.gemini`. Swapping models, or standing one up in a test, means
    satisfying this and nothing else.
    """

    def generate_structured(self, prompt: str, schema: type[TModel], mock: TModel | None = None) -> TModel:
        """Return a response validated against `schema`."""
        ...

    def structure_text(self, text: str, schema: type[TModel], instruction: str, mock: TModel | None = None) -> TModel:
        """Convert prose the model already produced into `schema`."""
        ...

    def start_chat(self, initial_history: list[HistoryTurn] | None = None, enable_search: bool = False) -> ChatSession:
        """Open a conversation, optionally seeded with prior turns."""
        ...

    def parse_trade_string(self, text: str) -> TradeProposal:
        """Parse a natural-language trade into the two sides."""
        ...


@runtime_checkable
class SportProvider(Protocol):
    """One sport on one platform."""

    sport: str
    """Short key: 'nba', 'nfl', 'fpl'."""

    label: str
    """Human name for pickers: 'NBA (Yahoo)'."""

    def list_leagues(self) -> list[LeagueRef]:
        """Every league this user plays in for the current season.

        Raises:
            FrontOfficeError: the platform is unreachable or unconfigured.
        """
        ...

    def build_context(self, league_id: str) -> SportContext:
        """Gather this league's state and render the scouting prompt.

        Raises:
            FrontOfficeError: the league or the user's team within it is missing.
        """
        ...

    def squad_rows(self, league_id: str) -> list[dict[str, str]]:
        """The user's roster as table rows, for a team view.

        Cheaper than build_context — a roster listing should not pull
        projections and a waiver pool.
        """
        ...


@runtime_checkable
class TradeProvider(Protocol):
    """A sport that can also evaluate trades.

    Separate from SportProvider because trade support arrives per sport: a
    provider can scout without yet being able to price a trade, and the registry
    advertises which can via `supports_trades`.
    """

    sport: str
    label: str

    def build_trade_context(self, league_id: str, proposal: TradeProposal) -> SportContext:
        """Resolve both sides of the trade and render the evaluation prompt.

        Raises:
            PlayerNotFoundError: a named player could not be resolved. Silently
                dropping one would evaluate a different trade than was asked.
        """
        ...
