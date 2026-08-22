"""NBA stats and schedule from nba_api, cached on disk.

Invalidation is tied to when games start and end rather than a plain TTL, so a
report never mixes yesterday's box scores into a live matchup.
"""

import json
import logging
import time
from datetime import date, datetime, timezone
from datetime import time as dt_time
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from nba_api.stats.endpoints import leaguegamelog, scheduleleaguev2  # type: ignore[import-untyped]
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from the_front_office.adapters.outbound.platforms.nba_stats.stats import extract_nine_cat
from the_front_office.adapters.outbound.platforms.nba_stats.types import (
    GameLogRecord,
    GameRecord,
    LeagueGamelogCache,
    NBACacheData,
    PlayerStats,
    ScheduleCache,
)
from the_front_office.config.settings import settings

logger = logging.getLogger(__name__)

SCHEDULE_TTL_HOURS = 24
SCHEDULE_TIMEOUT_SECONDS = 30

RETRY_MAX_ATTEMPTS = 3
RETRY_MULTIPLIER = 5.0
RETRY_MIN_WAIT = 5.0
RETRY_MAX_WAIT = 40.0

# nba_api wraps requests; these are the transient failures worth a second try.
# stats.nba.com rate-limits by stalling the connection, so timeouts dominate.
_RETRYABLE_NETWORK_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


def _is_nba_retryable_error(exc: BaseException) -> bool:
    """Decide whether an nba_api failure is transient.

    Retries on: network timeouts/connection drops, 5xx, and the invalid-JSON
    response nba_api raises when stats.nba.com serves a rate-limit stub.

    Does NOT retry on: 4xx client errors, or the KeyError/TypeError that means
    the response shape changed — retrying those just burns the rate-limit budget
    on a request that will fail identically.
    """
    if isinstance(exc, _RETRYABLE_NETWORK_EXCEPTIONS):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        return response is not None and response.status_code >= 500
    # nba_api raises a bare Exception for a non-JSON body, which is what a
    # throttled response looks like.
    return type(exc) is Exception and "InvalidResponse" in str(exc)


def _nba_retry() -> Retrying:
    """Build a tenacity Retrying instance for nba_api calls."""
    return Retrying(
        stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(
            multiplier=RETRY_MULTIPLIER,
            min=RETRY_MIN_WAIT,
            max=RETRY_MAX_WAIT,
        ),
        retry=retry_if_exception(_is_nba_retryable_error),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


# The NBA schedules by US Pacific time, so the boundaries are anchored there
# rather than to the machine's own zone.
PACIFIC = ZoneInfo("America/Los_Angeles")

PLAYER_STATS_INVALIDATION_TIMES = [
    dt_time(1, 0),  # 1:00 AM PT — after the last game ends
    dt_time(15, 0),  # 3:00 PM PT — before the first game starts
]


def _utc_now() -> datetime:
    """Current time as an aware UTC datetime — what gets written to the cache."""
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime | None:
    """Parse a stored cache timestamp into an aware datetime.

    A naive timestamp is unusable: without a zone it cannot be placed on a
    timeline, so it is treated as absent and the value refetched.
    """
    # fromisoformat accepts a trailing "Z" only from 3.11, and every NBA
    # timestamp has one.
    normalised = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


class NBAStatsClient:
    """Fetches NBA stats and schedule, backed by `.nba_cache.json`.

    The cache holds two independently-dated sections: `league_gamelog`, keyed by
    player name, and `schedule`, keyed by team tricode.
    """

    def __init__(self) -> None:
        self._last_call_time: float = 0.0
        self._cache_file: Path = Path(settings.nba_cache_file)
        self._cache_data: NBACacheData = {
            "league_gamelog": {"games": {}, "updated_at": ""},
            "schedule": {"teams": {}, "updated_at": ""},
        }
        self._load_cache()

    # ── Cache I/O ──────────────────────────────────────────────────

    def _load_cache(self) -> None:
        """Load unified cache from disk."""
        if not self._cache_file.exists():
            return

        try:
            raw_data = json.loads(self._cache_file.read_text(encoding="utf-8"))

            league_gamelog = cast("LeagueGamelogCache", raw_data.get("league_gamelog", {"games": {}, "updated_at": ""}))
            schedule = cast("ScheduleCache", raw_data.get("schedule", {"teams": {}, "updated_at": ""}))

            self._cache_data = {"league_gamelog": league_gamelog, "schedule": schedule}

            num_players = len(self._cache_data["league_gamelog"]["games"])
            logger.debug(
                f"Loaded NBA cache: {num_players} players in gamelog, "
                f"schedule is {self._get_schedule_age_hours():.1f}h old."
            )
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}. Starting fresh.")
            self._cache_data = {
                "league_gamelog": {"games": {}, "updated_at": ""},
                "schedule": {"teams": {}, "updated_at": ""},
            }

    def _save_cache(self) -> None:
        """Persist unified cache to disk."""
        try:
            self._cache_file.write_text(json.dumps(self._cache_data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def _get_schedule_age_hours(self, now: datetime | None = None) -> float:
        """Age of the cached schedule in hours, or 999.0 if it cannot be dated."""
        ts = _parse_timestamp(self._cache_data["schedule"].get("updated_at", ""))
        if ts is None:
            return 999.0
        return ((now or _utc_now()) - ts).total_seconds() / 3600

    def _is_league_gamelog_stale(self, now: datetime | None = None) -> bool:
        """Whether the gamelog has crossed a 1AM/3PM *Pacific* invalidation boundary.

        Args:
            now: override the current time; must be timezone-aware. For tests.
        """
        updated_at = _parse_timestamp(self._cache_data["league_gamelog"]["updated_at"])
        if updated_at is None:
            return True

        # Both sides are converted to Pacific so the comparison is against the
        # zone the boundaries are defined in, whatever the machine's own is.
        now_pt = (now or _utc_now()).astimezone(PACIFIC)
        updated_pt = updated_at.astimezone(PACIFIC)

        # From an earlier Pacific day: stale relative to today's boundaries.
        if updated_pt.date() < now_pt.date():
            return True

        # Updated today — stale only if a boundary fell between then and now.
        for boundary_time in PLAYER_STATS_INVALIDATION_TIMES:
            boundary = datetime.combine(now_pt.date(), boundary_time, tzinfo=PACIFIC)
            if updated_pt < boundary <= now_pt:
                return True
        return False

    # ── Rate Limiting ──────────────────────────────────────────────

    def _wait_for_rate_limit(self) -> None:
        """Ensures at least `nba_api_delay` seconds between calls."""
        elapsed = time.time() - self._last_call_time
        if elapsed < settings.nba_api_delay:
            time.sleep(settings.nba_api_delay - elapsed)
        self._last_call_time = time.time()

    # ── Player Stats ───────────────────────────────────────────────

    def _fetch_league_gamelog_frame(self) -> pd.DataFrame:
        """One nba_api call for the full-season player gamelog."""
        self._wait_for_rate_limit()
        # A much larger timeout than other calls: this pulls the entire
        # season's table in one request.
        log = leaguegamelog.LeagueGameLog(player_or_team_abbreviation="P", timeout=60)
        return log.get_data_frames()[0]

    def _ensure_league_gamelog_loaded(self) -> None:
        if not self._is_league_gamelog_stale():
            return

        logger.debug("Refreshing league gamelog via nba_api...")
        try:
            df = _nba_retry()(self._fetch_league_gamelog_frame)

            games_by_player: dict[str, list[GameLogRecord]] = {}
            # to_dict("records") rather than itertuples: the values are plain
            # objects we convert explicitly, which keeps the cache
            # JSON-serialisable and the dict key a real str.
            for row in df.to_dict("records"):
                player_name = str(row["PLAYER_NAME"])
                record: GameLogRecord = {
                    "GAME_DATE": str(row["GAME_DATE"]),
                    "PTS": float(row["PTS"]),
                    "REB": float(row["REB"]),
                    "AST": float(row["AST"]),
                    "STL": float(row["STL"]),
                    "BLK": float(row["BLK"]),
                    "TOV": float(row["TOV"]),
                    "FG3M": float(row["FG3M"]),
                    "FGA": float(row["FGA"]),
                    "FGM": float(row["FGM"]),
                    "FTA": float(row["FTA"]),
                    "FTM": float(row["FTM"]),
                }
                games_by_player.setdefault(player_name, []).append(record)

            self._cache_data["league_gamelog"] = {
                "games": games_by_player,
                "updated_at": _utc_now().isoformat(),
            }
            self._save_cache()
        except Exception as e:
            logger.warning(f"Failed to fetch league gamelog: {e}")

    def get_player_stats(self, full_name: str) -> PlayerStats | None:
        """Fetch recent stats (L5/L10/L15) for a player using the cached league gamelog."""
        self._ensure_league_gamelog_loaded()
        games = self._cache_data["league_gamelog"]["games"].get(full_name)

        if not games:
            return None

        games.sort(key=lambda g: g["GAME_DATE"], reverse=True)

        stats_dict: PlayerStats = PlayerStats()
        for count in [5, 10, 15]:
            if len(games) >= count:
                stats_dict[f"last_{count}"] = extract_nine_cat(games[:count])  # type: ignore[literal-required]

        return stats_dict if stats_dict else None

    # ── Schedule ───────────────────────────────────────────────────

    def _fetch_schedule_dict(self) -> dict[str, Any]:
        """One nba_api call for the full-season league schedule."""
        self._wait_for_rate_limit()
        return scheduleleaguev2.ScheduleLeagueV2(timeout=SCHEDULE_TIMEOUT_SECONDS).get_dict()

    def _schedule_predates_tipoff_field(self) -> bool:
        """Whether the cached schedule was written before tipoff_utc existed."""
        for games in self._cache_data["schedule"]["teams"].values():
            if games:
                return "tipoff_utc" not in games[0]
        return False

    def _ensure_schedule_loaded(self) -> None:
        """Fetch full season schedule via nba_api if stale, missing, or outdated in shape."""
        fresh = self._cache_data["schedule"]["updated_at"] and self._get_schedule_age_hours() < SCHEDULE_TTL_HOURS
        if fresh and not self._schedule_predates_tipoff_field():
            return

        logger.debug("Refreshing NBA schedule via nba_api...")
        try:
            data = _nba_retry()(self._fetch_schedule_dict)

            team_games: dict[str, list[GameRecord]] = {}
            for game_date_obj in data["leagueSchedule"]["gameDates"]:
                for game in game_date_obj["games"]:
                    game_info: GameRecord = {
                        # gameDateEst is midnight-anchored: a date label, not
                        # a timestamp. It equals the Eastern tip-off date,
                        # since no game tips after 23:00 ET.
                        "date": str(game["gameDateEst"])[:10],
                        "tipoff_utc": str(game["gameDateTimeUTC"]),
                        "status": int(game["gameStatus"]),
                        "home": str(game["homeTeam"]["teamTricode"]),
                        "away": str(game["awayTeam"]["teamTricode"]),
                    }
                    team_games.setdefault(game_info["home"], []).append(game_info)
                    team_games.setdefault(game_info["away"], []).append(game_info)

            self._cache_data["schedule"] = {"teams": team_games, "updated_at": _utc_now().isoformat()}
            self._save_cache()
        except Exception as e:
            logger.warning(f"Failed to fetch NBA schedule: {e}")

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date, now: datetime | None = None) -> int:
        """Count a team's not-yet-started games inside a matchup window.

        Two notions of time, kept apart:

        * The **window** test compares game-date labels, which is what Yahoo's
          matchup dates also mean — labels to labels, no zone question.
        * The **already-played** test uses the tip-off instant in UTC, so the
          answer does not depend on the machine's zone.

        "Remaining" means not yet started. The status filter still runs, since a
        cached schedule can be hours old and its statuses stale.

        Args:
            now: override the current instant; must be timezone-aware.
        """
        self._ensure_schedule_loaded()
        games = self._cache_data["schedule"]["teams"].get(team_abbr.upper(), [])
        moment = now or _utc_now()

        count = 0
        for g in games:
            if not (start_date <= date.fromisoformat(g["date"]) <= end_date):
                continue
            if g["status"] not in (1, 2):
                continue
            tipoff = _parse_timestamp(g["tipoff_utc"])
            if tipoff is None or tipoff <= moment:
                continue
            count += 1
        return count

    def get_remaining_games_bulk(
        self, team_abbrs: list[str], start_date: date, end_date: date, now: datetime | None = None
    ) -> dict[str, int]:
        """Bulk count remaining games. One schedule load, one `now` for all teams."""
        self._ensure_schedule_loaded()
        moment = now or _utc_now()
        return {
            abbr.upper(): self.get_remaining_games(abbr, start_date, end_date, now=moment) for abbr in set(team_abbrs)
        }
