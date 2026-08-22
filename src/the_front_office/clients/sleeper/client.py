"""Sleeper API client.

Sleeper is public and read-only: no OAuth, no API key. The whole surface is
plain GETs, which is why the football path has nothing resembling the Yahoo
login flow.

Sleeper asks callers to stay under 1000 requests/minute and to fetch the player
catalogue "once per day at most". Everything cacheable is cached on disk with a
TTL chosen per endpoint: the catalogue daily, projections for a settled week
effectively forever, trending for an hour.
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from the_front_office.cache import JsonDiskCache
from the_front_office.clients.sleeper.types import (
    NFLState,
    PlayerMeta,
    Projection,
    ScoringFormat,
    SleeperLeague,
    SleeperRoster,
    SleeperUser,
    TrendingPlayer,
)
from the_front_office.config.settings import settings
from the_front_office.exceptions import SleeperAPIError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sleeper.app/v1"
PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl"

REQUEST_TIMEOUT_SECONDS = 30
CATALOGUE_TIMEOUT_SECONDS = 90  # the player catalogue is ~14MB

# TTLs, chosen from how quickly each endpoint's data actually changes.
PLAYERS_TTL = timedelta(days=1)  # the docs ask for at most one fetch per day
PROJECTIONS_TTL = timedelta(hours=6)
STATS_TTL = timedelta(hours=6)
TRENDING_TTL = timedelta(hours=1)
LEAGUE_TTL = timedelta(hours=6)
ROSTERS_TTL = timedelta(minutes=10)  # changes on every waiver claim
MATCHUPS_TTL = timedelta(minutes=2)  # live scores during games
STATE_TTL = timedelta(hours=1)

RETRY_MAX_ATTEMPTS = 3

_RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


def _is_retryable(exc: BaseException) -> bool:
    """Whether a Sleeper failure is transient.

    Retries network errors, 5xx, and 429 (Sleeper's documented rate-limit code).
    A 404 means the league or user does not exist and will never succeed.
    """
    if isinstance(exc, _RETRYABLE_NETWORK_EXCEPTIONS):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code == 429 or response.status_code >= 500
    return False


def _retry() -> Retrying:
    return Retrying(
        stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


class SleeperClient:
    """Read-only access to Sleeper's fantasy and NFL data."""

    def __init__(self, cache: JsonDiskCache | None = None, session: Any = None) -> None:
        self._cache = cache or JsonDiskCache(Path(settings.sleeper_cache_file))
        self._session = session or requests.Session()

    # ── transport ───────────────────────────────────────────────────

    def _get(self, url: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Any:
        """One GET, retried on transient failures, raising a domain error otherwise."""

        def _request() -> Any:
            response = self._session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()

        try:
            return _retry()(_request)
        except Exception as e:
            logger.error(f"Sleeper request failed ({url}): {e}")
            raise SleeperAPIError(f"Sleeper request failed: {e}") from e

    def _cached(self, key: str, url: str, ttl: timedelta, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Any:
        hit = self._cache.get(key, ttl)
        if hit is not None:
            logger.debug(f"Sleeper cache hit: {key}")
            return hit
        value = self._get(url, timeout=timeout)
        self._cache.set(key, value)
        return value

    # ── league state ────────────────────────────────────────────────

    def get_nfl_state(self) -> NFLState:
        """Current week and season type."""
        data = self._cached("state", f"{BASE_URL}/state/nfl", STATE_TTL)
        return NFLState(
            week=int(data.get("week", 0)),
            season=str(data.get("season", "")),
            season_type=str(data.get("season_type", "")),
            display_week=int(data.get("display_week") or data.get("week") or 0),
        )

    def get_user(self, username: str) -> SleeperUser:
        """Resolve a username to a user. Usernames change; user_ids do not."""
        data = self._get(f"{BASE_URL}/user/{username}")
        if not data:
            raise SleeperAPIError(f"No Sleeper user named {username!r}.")
        return SleeperUser(
            user_id=str(data["user_id"]),
            username=str(data.get("username") or username),
            display_name=str(data.get("display_name") or username),
        )

    def get_leagues(self, user_id: str, season: str) -> list[SleeperLeague]:
        """Every NFL league a user is in for a season."""
        data = self._cached(
            f"leagues_{user_id}_{season}",
            f"{BASE_URL}/user/{user_id}/leagues/nfl/{season}",
            LEAGUE_TTL,
        )
        return [self._to_league(item) for item in data or []]

    @staticmethod
    def _to_league(data: dict[str, Any]) -> SleeperLeague:
        settings_blob = data.get("scoring_settings") or {}
        return SleeperLeague(
            league_id=str(data["league_id"]),
            name=str(data.get("name", "Unnamed league")),
            season=str(data.get("season", "")),
            total_rosters=int(data.get("total_rosters", 0)),
            scoring_format=SleeperClient.detect_scoring_format(settings_blob),
            roster_positions=[str(p) for p in data.get("roster_positions") or []],
        )

    @staticmethod
    def detect_scoring_format(scoring_settings: dict[str, Any]) -> ScoringFormat:
        """Infer PPR / half-PPR / standard from the league's per-reception value.

        Sleeper does not label the format; it exposes the `rec` setting, which is
        points per reception. Everything downstream reads the matching projection
        field, so getting this wrong would silently rank players by the wrong
        currency.
        """
        rec = float(scoring_settings.get("rec", 0) or 0)
        if rec >= 0.75:
            return "pts_ppr"
        if rec >= 0.25:
            return "pts_half_ppr"
        return "pts_std"

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        data = self._cached(f"rosters_{league_id}", f"{BASE_URL}/league/{league_id}/rosters", ROSTERS_TTL)
        rosters = []
        for item in data or []:
            record = item.get("settings") or {}
            rosters.append(
                SleeperRoster(
                    roster_id=int(item.get("roster_id", 0)),
                    owner_id=str(item.get("owner_id") or ""),
                    player_ids=[str(p) for p in item.get("players") or []],
                    starter_ids=[str(p) for p in item.get("starters") or []],
                    wins=int(record.get("wins", 0)),
                    losses=int(record.get("losses", 0)),
                    ties=int(record.get("ties", 0)),
                    points_for=float(record.get("fpts", 0)) + float(record.get("fpts_decimal", 0)) / 100,
                )
            )
        return rosters

    def get_league_users(self, league_id: str) -> dict[str, str]:
        """Map user_id -> display name, for labelling opponents."""
        data = self._cached(f"users_{league_id}", f"{BASE_URL}/league/{league_id}/users", LEAGUE_TTL)
        return {str(u["user_id"]): str(u.get("display_name") or u.get("username") or "Unknown") for u in data or []}

    def get_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        """Raw matchup entries for a week — one per roster, paired by matchup_id."""
        return (
            self._cached(
                f"matchups_{league_id}_{week}",
                f"{BASE_URL}/league/{league_id}/matchups/{week}",
                MATCHUPS_TTL,
            )
            or []
        )

    # ── player data ─────────────────────────────────────────────────

    def get_players(self) -> dict[str, PlayerMeta]:
        """The player catalogue, trimmed to the fields we use.

        The raw response is ~14MB across 12k players. Only a handful of fields
        matter here, so the cache stores the trimmed form — the full payload
        would dominate the cache file for no benefit.
        """
        cached = self._cache.get("players", PLAYERS_TTL)
        if cached is not None:
            return cached

        raw = self._get(f"{BASE_URL}/players/nfl", timeout=CATALOGUE_TIMEOUT_SECONDS)
        trimmed: dict[str, PlayerMeta] = {}
        for player_id, p in (raw or {}).items():
            if not isinstance(p, dict):
                continue
            name = p.get("full_name") or " ".join(filter(None, [p.get("first_name"), p.get("last_name")]))
            trimmed[str(player_id)] = PlayerMeta(
                player_id=str(player_id),
                name=str(name or player_id),
                position=str(p.get("position") or ""),
                team=str(p.get("team") or "FA"),
                status=str(p.get("status") or ""),
                injury_status=str(p.get("injury_status") or ""),
                depth_chart_order=int(p.get("depth_chart_order") or 0),
                years_exp=int(p.get("years_exp") or 0),
            )
        self._cache.set("players", trimmed)
        logger.debug(f"Cached {len(trimmed)} players from Sleeper")
        return trimmed

    def get_projections(self, season: str, week: int, scoring: ScoringFormat) -> dict[str, Projection]:
        """Weekly projections keyed by player_id.

        This is the forward-looking number the whole football report rests on:
        start/sit and waiver value are both "who will score most this week".
        """
        url = f"{PROJECTIONS_URL}/{season}/{week}?season_type=regular&order_by={scoring}" + "".join(
            f"&position[]={p}" for p in ("QB", "RB", "WR", "TE", "K", "DEF")
        )
        data = self._cached(f"proj_{season}_{week}_{scoring}", url, PROJECTIONS_TTL)

        projections: dict[str, Projection] = {}
        for row in data or []:
            player = row.get("player") or {}
            stats = row.get("stats") or {}
            points = stats.get(scoring)
            if points is None:
                continue
            player_id = str(row.get("player_id") or "")
            name = " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
            projections[player_id] = Projection(
                player_id=player_id,
                name=name or player_id,
                position=str(player.get("position") or ""),
                team=str(player.get("team") or row.get("team") or "FA"),
                opponent=str(row.get("opponent") or ""),
                points=float(points),
                injury_status=str(player.get("injury_status") or ""),
            )
        return projections

    def get_stats(self, season: str, week: int) -> dict[str, dict[str, float]]:
        """Actual per-player stats for a completed week."""
        data = self._cached(f"stats_{season}_{week}", f"{BASE_URL}/stats/nfl/regular/{season}/{week}", STATS_TTL)
        return {str(k): v for k, v in (data or {}).items() if isinstance(v, dict)}

    def get_trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list[TrendingPlayer]:
        """Most-added or most-dropped players across all of Sleeper.

        A useful independent signal: the crowd often reacts to a depth-chart
        change or an injury before projections catch up.
        """
        url = f"{BASE_URL}/players/nfl/trending/{kind}?lookback_hours={lookback_hours}&limit={limit}"
        data = self._cached(f"trending_{kind}_{lookback_hours}_{limit}", url, TRENDING_TTL)
        return [
            TrendingPlayer(player_id=str(item["player_id"]), count=int(item.get("count", 0)))
            for item in data or []
            if item.get("player_id")
        ]
