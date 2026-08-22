"""Which sports exist, and whether each one is usable right now.

Without this, every entry point hardcodes the provider list — `main.py` and
`ui/app.py` each named NBAProvider and SleeperNFLProvider, so adding a sport
meant editing both and remembering the CLI, the UI and the help text. Now a
sport registers itself here and every surface picks it up.

`is_configured` matters as much as `build`: a football-only user has no Yahoo
credentials, and the CLI must not open an OAuth flow for a sport they do not
play.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from the_front_office.application.scouting import ScoutEngine
from the_front_office.application.trading import TradeEngine
from the_front_office.config.settings import settings
from the_front_office.domain.ports import AnalysisModel, SportProvider, TradeProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SportEntry:
    """One registered sport."""

    sport: str
    label: str
    build: Callable[[], SportProvider]
    is_configured: Callable[[], bool]
    requires: str
    """What to put in .env to enable it, quoted in the 'not configured' message."""

    supports_trades: bool = False
    """Whether trade evaluation works for this sport.

    Declared here rather than tested as `sport == "nba"` at each call site, so
    adding trade support to a sport is a flag rather than a hunt through the CLI
    and the UI.
    """


def _build_nfl() -> SportProvider:
    from the_front_office.adapters.outbound.sports.nfl.sleeper import SleeperNFLProvider

    return SleeperNFLProvider()


def _build_nba() -> SportProvider:
    """Yahoo needs an authenticated context and a specific league object.

    The handshake is deferred to here so that constructing the registry — which
    every entry point does at startup — never triggers a browser OAuth flow.
    """
    from the_front_office.adapters.outbound.platforms.yahoo.client import YahooFantasyClient
    from the_front_office.adapters.outbound.sports.nba.yahoo import YahooNBAProvider

    YahooFantasyClient.login()
    ctx = YahooFantasyClient.get_context()
    leagues = list(ctx.get_leagues("nba", YahooNBAProvider.season_year()))
    if not leagues:
        from the_front_office.domain.errors import LeagueNotFoundError

        raise LeagueNotFoundError("no Yahoo NBA leagues for this season")
    return YahooNBAProvider(leagues[0], all_leagues=leagues)


REGISTRY: tuple[SportEntry, ...] = (
    SportEntry(
        sport="nba",
        label="NBA (Yahoo)",
        build=_build_nba,
        is_configured=lambda: bool(settings.yahoo_client_id and settings.yahoo_client_secret),
        requires="YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET",
        supports_trades=True,
    ),
    SportEntry(
        sport="nfl",
        label="NFL (Sleeper)",
        build=_build_nfl,
        is_configured=lambda: bool(settings.sleeper_username),
        requires="SLEEPER_USERNAME",
    ),
)


def all_sports() -> tuple[SportEntry, ...]:
    return REGISTRY


def configured_sports() -> list[SportEntry]:
    """Only the sports this user has credentials for."""
    return [entry for entry in REGISTRY if entry.is_configured()]


def requirements_summary() -> str:
    """One line naming what to set for each sport, for a 'nothing configured' message."""
    return "; ".join(f"{e.label}: {e.requires}" for e in REGISTRY)


def find(sport: str) -> SportEntry | None:
    key = sport.lower().lstrip("/")
    return next((e for e in REGISTRY if e.sport == key), None)


# ── models and engines ──────────────────────────────────────────────────


def default_model(mock_mode: bool = False) -> AnalysisModel:
    """The configured language model.

    The single place the vendor is named. Imported lazily so that merely
    importing the composition root does not pull in the SDK.
    """
    from the_front_office.adapters.outbound.llm.gemini.client import GeminiClient

    return GeminiClient(mock_mode=mock_mode)


def scout_engine(provider: SportProvider, mock_ai: bool = False) -> ScoutEngine:
    """A scouting engine wired to the configured model."""
    return ScoutEngine(provider, ai=default_model(mock_ai))


def trade_engine(provider: TradeProvider, mock_ai: bool = False) -> TradeEngine:
    """A trade engine wired to the configured model."""
    return TradeEngine(provider, ai=default_model(mock_ai))
