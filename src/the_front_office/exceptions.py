"""Domain exceptions.

Services raise these instead of returning `None`, `[]` or an error string that
the caller cannot distinguish from a real result. The CLI layer in `main.py`
catches `FrontOfficeError` and renders it; nothing else prints.
"""


class FrontOfficeError(Exception):
    """Base class for every expected, user-facing failure."""


class TeamNotFoundError(FrontOfficeError):
    """The current Yahoo login does not own a team in this league."""

    def __init__(self, league_name: str) -> None:
        super().__init__(f"Could not identify your team in {league_name}. Are you a manager in this league?")
        self.league_name = league_name


class YahooAPIError(FrontOfficeError):
    """A Yahoo Fantasy API call failed.

    Distinct from an empty result: `search_players` returning no matches is a
    valid answer, while a failed request is not.
    """


class PlayerNotFoundError(FrontOfficeError):
    """One or more player names in a trade could not be resolved."""

    def __init__(self, names: list[str]) -> None:
        joined = ", ".join(names)
        super().__init__(
            f"Could not find {'these players' if len(names) > 1 else 'this player'} in the league: {joined}. "
            "Check the spelling, or use the full name as it appears on Yahoo."
        )
        self.names = names


class TradeParseError(FrontOfficeError):
    """The trade description could not be parsed into two sides."""

    def __init__(self, text: str) -> None:
        super().__init__(f"Could not parse the trade from {text!r}. Use the form: 'Give <players>, Get <players>'.")
        self.text = text


class AIUnavailableError(FrontOfficeError):
    """Gemini is not usable — no API key, or the client failed to initialise."""

    def __init__(self, detail: str = "GOOGLE_API_KEY is not set") -> None:
        super().__init__(f"AI features unavailable: {detail}. Use --mock to run without credentials.")


class AIResponseError(FrontOfficeError):
    """Gemini was reachable but the call failed or returned nothing usable."""
