"""Provider lifetime for one CLI session."""

from thefrontoffice.bootstrap import CompetitionEntry
from thefrontoffice.domain.ports import CompetitionProvider


class Session:
    """Holds providers, building each on first use.

    Construction is deferred because building a provider can open an OAuth
    flow, which a user who does not play that competition must never be made to sit
    through.
    """

    def __init__(self) -> None:
        self._providers: dict[str, CompetitionProvider] = {}

    def provider(self, entry: CompetitionEntry) -> CompetitionProvider:
        if entry.competition not in self._providers:
            self._providers[entry.competition] = entry.build()
        return self._providers[entry.competition]
