"""NBA stats and schedule from nba_api, cached on disk.

Invalidation is tied to when games start and end rather than a plain TTL, so a
report never mixes yesterday's box scores into a live matchup.
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from nba_api.stats.endpoints import leaguegamelog, scheduleleaguev2  # type: ignore[import-untyped]
from tenacity import Retrying

from the_front_office.adapters.outbound.platforms.cache import JsonDiskCache
from the_front_office.adapters.outbound.platforms.nba_stats.stats import extract_nine_cat
from the_front_office.adapters.outbound.platforms.nba_stats.types import (
    GameLogRecord,
    GameRecord,
    PlayerStats,
)
from the_front_office.adapters.outbound.platforms.retry import build_retry, is_transient
from the_front_office.config.settings import settings

logger = logging.getLogger(__name__)

SCHEDULE_TTL_HOURS = 24
SCHEDULE_TTL = timedelta(hours=SCHEDULE_TTL_HOURS)

GAMELOG_KEY = "league_gamelog"
SCHEDULE_KEY = "schedule"
SCHEDULE_TIMEOUT_SECONDS = 30

RETRY_MAX_ATTEMPTS = 3
RETRY_MULTIPLIER = 5.0
RETRY_MIN_WAIT = 5.0
RETRY_MAX_WAIT = 40.0


# nba_api wraps requests; these are the transient failures worth a second try.
# stats.nba.com rate-limits by stalling the connection, so timeouts dominate.
def _is_nba_retryable_error(exc: BaseException) -> bool:
    """Whether an nba_api failure is transient.

    Adds the bare Exception nba_api raises for a non-JSON body, which is what a
    throttled response from stats.nba.com looks like.
    """
    if is_transient(exc):
        return True
    return type(exc) is Exception and "InvalidResponse" in str(exc)


def _nba_retry() -> Retrying:
    return build_retry(
        attempts=RETRY_MAX_ATTEMPTS,
        multiplier=RETRY_MULTIPLIER,
        min_wait=RETRY_MIN_WAIT,
        max_wait=RETRY_MAX_WAIT,
        predicate=_is_nba_retryable_error,
    )


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
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
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

    def __init__(self, cache: JsonDiskCache | None = None) -> None:
        self._last_call_time: float = 0.0
        # The same store every other platform uses. What is different here is
        # not where the answer is kept but when it stops being true, and that
        # is a freshness rule rather than a second cache.
        self._cache = cache or JsonDiskCache(Path(settings.nba_cache_file))
        self._gamelog: dict[str, list[GameLogRecord]] = {}
        self._schedule: dict[str, list[GameRecord]] = {}

    # ── Freshness ──────────────────────────────────────────────────

    @staticmethod
    def _gamelog_is_fresh(stored_at: datetime, now: datetime) -> bool:
        """Good until the next 1AM/3PM *Pacific* boundary passes.

        The rule a TTL cannot express, and the reason a freshness rule is a
        predicate: the gamelog is worth refetching when the day's games have
        been played and settled, which is a moment on the league's own clock,
        not an interval after whenever it happened to be fetched.
        """
        # Both sides in Pacific, so the comparison is against the zone the
        # boundaries are defined in, whatever the machine's own is.
        now_pt = now.astimezone(PACIFIC)
        stored_pt = stored_at.astimezone(PACIFIC)

        # From an earlier Pacific day: stale relative to today's boundaries.
        if stored_pt.date() < now_pt.date():
            return False

        # Stored today — stale only if a boundary fell between then and now.
        for boundary_time in PLAYER_STATS_INVALIDATION_TIMES:
            boundary = datetime.combine(now_pt.date(), boundary_time, tzinfo=PACIFIC)
            if stored_pt < boundary <= now_pt:
                return False
        return True

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
        hit = self._cache.get(GAMELOG_KEY, self._gamelog_is_fresh)
        if hit is not None:
            self._gamelog = hit
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

            self._gamelog = games_by_player
            self._cache.set(GAMELOG_KEY, games_by_player)
        except Exception as e:
            # A failed refresh leaves whatever was already loaded in place:
            # stale numbers are worth more than none, and the caller cannot
            # tell an empty gamelog from a player who has not played.
            logger.warning(f"Failed to fetch league gamelog: {e}")

    def get_player_stats(self, full_name: str) -> PlayerStats | None:
        """Fetch recent stats (L5/L10/L15) for a player using the cached league gamelog."""
        self._ensure_league_gamelog_loaded()
        games = self._gamelog.get(full_name)

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

    @staticmethod
    def _predates_tipoff_field(teams: dict[str, list[GameRecord]]) -> bool:
        """Whether a cached schedule was written before tipoff_utc existed.

        Age is not the only way an entry stops being usable: one written by an
        older version of this code is fresh and still unreadable.
        """
        for games in teams.values():
            if games:
                return "tipoff_utc" not in games[0]
        return False

    def _ensure_schedule_loaded(self) -> None:
        """Fetch full season schedule via nba_api if stale, missing, or outdated in shape."""
        hit = self._cache.get(SCHEDULE_KEY, SCHEDULE_TTL)
        if hit is not None and not self._predates_tipoff_field(hit):
            self._schedule = hit
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

            self._schedule = team_games
            self._cache.set(SCHEDULE_KEY, team_games)
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
        games = self._schedule.get(team_abbr.upper(), [])
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
