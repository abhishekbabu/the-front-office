"""The composition root: the one module that names concrete implementations.

Registers the available sports and wires engines to a model. Everything else
works against ports.

`is_configured` gates whether a platform is contacted at all — building a
provider can open an OAuth flow, and a user who does not play that sport must
never be made to sit through one.
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


def _build_fpl() -> SportProvider:
    from the_front_office.adapters.outbound.sports.fpl.fpl import FPLProvider

    return FPLProvider()


def _build_nba() -> SportProvider:
    """Yahoo needs an authenticated context and a specific league object.

    The handshake is deferred to here so that constructing the registry — which
    every entry point does at startup — never triggers a browser OAuth flow.
    """
    from the_front_office.adapters.outbound.platforms.yahoo.client import YahooClient
    from the_front_office.adapters.outbound.sports.nba.yahoo import YahooNBAProvider

    YahooClient.login()
    ctx = YahooClient.get_context()
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
        supports_trades=True,
    ),
    SportEntry(
        sport="fpl",
        label="FPL (Fantasy Premier League)",
        build=_build_fpl,
        is_configured=lambda: bool(settings.fpl_entry_id),
        requires="FPL_ENTRY_ID",
        # FPL managers do not trade with each other; the equivalent move is a
        # transfer against the market, which the scouting report already covers.
        supports_trades=False,
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
