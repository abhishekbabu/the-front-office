"""Domain exceptions.

Raised instead of returning `None`, `[]` or an error string, none of which a
caller can tell apart from a real result. The inbound adapters catch
`FrontOfficeError` and render it; nothing else prints.
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


class YahooAuthError(FrontOfficeError):
    """Yahoo accepted the token and refused the request.

    Distinct from a bad token: the handshake succeeded, so re-authorising alone
    changes nothing. It means the developer app itself was never granted the
    Fantasy Sports scope, and every endpoint refuses identically.
    """

    def __init__(self) -> None:
        super().__init__(
            "Yahoo accepted the token and granted it nothing — every endpoint returns 403, "
            "including ones needing no permission at all, and the authorisation completes "
            "without ever showing a consent screen. That means the app itself carries no API "
            "permission, whatever the developer console displays. In order: (1) at "
            "https://developer.yahoo.com/apps/ press Update on the app and confirm Fantasy "
            "Sports → Read persists across a reload; (2) remove the app under Apps connected "
            "to your account at https://login.yahoo.com/account/security so the next "
            "authorisation has no stored grant to reuse; (3) failing both, create a new app "
            "with the permission set at creation — a permission added to an existing Yahoo "
            "app is unreliable — and put its Client ID and Secret in Settings. Then run "
            "`just yahoo-login --force`."
        )


class YahooLoginRequiredError(FrontOfficeError):
    """No cached Yahoo token, and this process cannot obtain one.

    The handshake opens a browser and waits, which is fine from a terminal and
    impossible inside a request handler — the caller would wait on a window it
    cannot see.
    """

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail
            or (
                "Yahoo is not authorised on this machine yet. Run `just yahoo-login` once; "
                "the token is cached in .yahoofantasy and reused after that."
            )
        )


class SleeperAPIError(FrontOfficeError):
    """A Sleeper API call failed.

    Distinct from an empty result: a league with no transactions this week is a
    valid answer, a failed request is not.
    """


class FPLAPIError(FrontOfficeError):
    """A Fantasy Premier League API call failed.

    Distinct from an empty result: a gameweek with no fixtures for your clubs is
    a valid answer, a failed request is not.
    """


class LeagueNotFoundError(FrontOfficeError):
    """The configured account has no matching league on its platform."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Could not find your league: {detail}")


class PlayerNotFoundError(FrontOfficeError):
    """One or more player names in a trade could not be resolved."""

    def __init__(self, names: list[str]) -> None:
        joined = ", ".join(names)
        super().__init__(
            f"Could not find {'these players' if len(names) > 1 else 'this player'} in the league: {joined}. "
            "Check the spelling, or use the full name as the platform shows it."
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
        super().__init__(
            f"AI features unavailable: {detail}. "
            "Turn on Mock AI — `--mock` on the CLI, or MOCK_AI in Settings — to run without credentials."
        )


class AIResponseError(FrontOfficeError):
    """Gemini was reachable but the call failed or returned nothing usable."""
