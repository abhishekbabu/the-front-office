"""Provider lifetime for one CLI session."""

from the_front_office.bootstrap import SportEntry
from the_front_office.domain.ports import SportProvider


class Session:
    """Holds providers, building each on first use.

    Deferring construction is what lets a football-only user reach `/football`:
    building the NBA provider opens a Yahoo OAuth flow, and doing that at
    startup made the CLI exit before the prompt for anyone without Yahoo
    credentials.
    """

    def __init__(self) -> None:
        self._providers: dict[str, SportProvider] = {}

    def provider(self, entry: SportEntry) -> SportProvider:
        if entry.sport not in self._providers:
            self._providers[entry.sport] = entry.build()
        return self._providers[entry.sport]
