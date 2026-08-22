"""Provider lifetime for one CLI session."""

from the_front_office.bootstrap import SportEntry
from the_front_office.domain.ports import SportProvider


class Session:
    """Holds providers, building each on first use.

    Construction is deferred because building a provider can open an OAuth
    flow, which a user who does not play that sport must never be made to sit
    through.
    """

    def __init__(self) -> None:
        self._providers: dict[str, SportProvider] = {}

    def provider(self, entry: SportEntry) -> SportProvider:
        if entry.sport not in self._providers:
            self._providers[entry.sport] = entry.build()
        return self._providers[entry.sport]
