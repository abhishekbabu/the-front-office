"""Sleeper API client.

Sleeper is public and read-only: no OAuth, no API key. The whole surface is
plain GETs, which is why the football path has nothing resembling the Yahoo
login flow.

Sleeper asks callers to stay under 1000 requests/minute and to fetch the player
catalog "once per day at most". Everything cacheable is cached on disk with a
TTL chosen per endpoint: the catalog daily, projections for a settled week
effectively forever, trending for an hour.
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from tenacity import Retrying

from the_front_office.adapters.outbound.platforms.cache import JsonDiskCache
from the_front_office.adapters.outbound.platforms.http import JsonApiClient
from the_front_office.adapters.outbound.platforms.retry import build_retry, is_transient
from the_front_office.adapters.outbound.platforms.sleeper.types import (
    GameProjection,
    PlayerMeta,
    ScoringFormat,
    SeasonState,
    SleeperLeague,
    SleeperRoster,
    SleeperUser,
    TrendingPlayer,
    WeeklyProjection,
)
from the_front_office.config.settings import settings
from the_front_office.domain.errors import SleeperAPIError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sleeper.app/v1"
PROJECTIONS_URL = "https://api.sleeper.app/projections"

# Sleeper serves several sports off the same shape. The football path uses "nfl";
# the basketball projections the NBA scout reads use "nba".
NFL = "nfl"
NBA = "nba"

REQUEST_TIMEOUT_SECONDS = 30
CATALOG_TIMEOUT_SECONDS = 90  # the player catalog is ~14MB

# TTLs, chosen from how quickly each endpoint's data actually changes.
PLAYERS_TTL = timedelta(days=1)  # the docs ask for at most one fetch per day
PROJECTIONS_TTL = timedelta(hours=6)
TRENDING_TTL = timedelta(hours=1)
LEAGUE_TTL = timedelta(hours=6)
ROSTERS_TTL = timedelta(minutes=10)  # changes on every waiver claim
MATCHUPS_TTL = timedelta(minutes=2)  # live scores during games
STATE_TTL = timedelta(hours=1)

RETRY_MAX_ATTEMPTS = 3

# Sleeper documents 429 for rate limiting; everything else transient is common.
RETRYABLE_STATUS = frozenset({429})


def _is_retryable(exc: BaseException) -> bool:
    """Whether a Sleeper failure is transient.

    A 404 means the league or user does not exist and will never succeed.
    """
    return is_transient(exc, RETRYABLE_STATUS)


def _retry() -> Retrying:
    return build_retry(attempts=RETRY_MAX_ATTEMPTS, multiplier=2, min_wait=2, max_wait=20, predicate=_is_retryable)


class SleeperClient:
    """Read-only access to Sleeper's fantasy and NFL data."""

    def __init__(self, cache: JsonDiskCache | None = None, session: Any = None) -> None:
        self._api = JsonApiClient(
            name="Sleeper",
            cache=cache or JsonDiskCache(Path(settings.sleeper_cache_file)),
            # Read through the module global rather than binding it here, so the
            # policy stays one thing a test can replace.
            retry=lambda: _retry(),
            error=SleeperAPIError,
            session=session,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    # ── transport ───────────────────────────────────────────────────

    def _get(self, url: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Any:
        return self._api.get(url, timeout=timeout)

    def _cached(self, key: str, url: str, ttl: timedelta, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Any:
        return self._api.cached(key, url, ttl, timeout=timeout)

    # ── league state ────────────────────────────────────────────────

    def get_state(self, sport: str = NFL) -> SeasonState:
        """Current week and season type for a sport."""
        data = self._cached(f"state_{sport}", f"{BASE_URL}/state/{sport}", STATE_TTL)
        return SeasonState(
            week=int(data.get("week", 0)),
            season=str(data.get("season", "")),
            season_type=str(data.get("season_type", "")),
        )

    def get_nfl_state(self) -> SeasonState:
        """Current NFL week and season type."""
        return self.get_state(NFL)

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

    def get_players(self, sport: str = NFL) -> dict[str, PlayerMeta]:
        """The player catalog, trimmed to the fields we use.

        The raw response is ~14MB across 12k players. Only a handful of fields
        matter here, so the cache stores the trimmed form — the full payload
        would dominate the cache file for no benefit.
        """
        cached = self._api.cache_get(f"players_{sport}", PLAYERS_TTL)
        if cached is not None:
            return cached

        raw = self._get(f"{BASE_URL}/players/{sport}", timeout=CATALOG_TIMEOUT_SECONDS)
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
        self._api.cache_set(f"players_{sport}", trimmed)
        logger.debug(f"Cached {len(trimmed)} {sport} players from Sleeper")
        return trimmed

    def get_projections(self, season: str, week: int, scoring: ScoringFormat) -> dict[str, WeeklyProjection]:
        """Weekly projections keyed by player_id.

        This is the forward-looking number the whole football report rests on:
        start/sit and waiver value are both "who will score most this week".
        """
        url = f"{PROJECTIONS_URL}/{season}/{week}?season_type=regular&order_by={scoring}" + "".join(
            f"&position[]={p}" for p in ("QB", "RB", "WR", "TE", "K", "DEF")
        )
        data = self._cached(f"proj_{season}_{week}_{scoring}", url, PROJECTIONS_TTL)

        projections: dict[str, WeeklyProjection] = {}
        for row in data or []:
            player = row.get("player") or {}
            stats = row.get("stats") or {}
            points = stats.get(scoring)
            if points is None:
                continue
            player_id = str(row.get("player_id") or "")
            name = " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
            projections[player_id] = WeeklyProjection(
                player_id=player_id,
                name=name or player_id,
                position=str(player.get("position") or ""),
                team=str(player.get("team") or row.get("team") or "FA"),
                opponent=str(row.get("opponent") or ""),
                points=float(points),
                injury_status=str(player.get("injury_status") or ""),
            )
        return projections

    def get_nba_projections(self, season: str, week: int) -> list[GameProjection]:
        """Per-game NBA projections for a Sleeper week.

        One row per player per game, each carrying a date, an opponent and the
        full nine-category line. Summing a player's rows across a matchup period
        gives projected category totals — which is what a category league
        actually needs, and what the NBA scout had no source for.

        Returns an empty list out of season: Sleeper publishes nothing before
        opening night, and the scout falls back to recent form alone.
        """
        url = f"{PROJECTIONS_URL}/{NBA}/{season}/{week}?season_type=regular&order_by=pts" + "".join(
            f"&position[]={p}" for p in ("PG", "SG", "SF", "PF", "C")
        )
        data = self._cached(f"proj_{NBA}_{season}_{week}", url, PROJECTIONS_TTL)

        projections: list[GameProjection] = []
        for row in data or []:
            stats = row.get("stats") or {}
            if stats.get("pts") is None:
                continue
            player = row.get("player") or {}
            name = " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
            projections.append(
                GameProjection(
                    player_id=str(row.get("player_id") or ""),
                    name=name,
                    team=str(player.get("team") or row.get("team") or ""),
                    opponent=str(row.get("opponent") or ""),
                    date=str(row.get("date") or "")[:10],
                    stats={k: float(v) for k, v in stats.items() if isinstance(v, int | float)},
                )
            )
        return projections

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
