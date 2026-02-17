"""
NBA.com Data Client (via nba_api).
Provides player stats and schedule data with a unified local cache.
"""
import time
import json
import logging
from pathlib import Path
from datetime import datetime, date, time as dt_time
from typing import Optional, Dict, cast
import pandas as pd
from nba_api.stats.static import players, teams  # type: ignore[import-untyped]
from nba_api.stats.endpoints import playergamelog, scheduleleaguev2  # type: ignore[import-untyped]
from the_front_office.config.settings import NBA_API_DELAY, NBA_CACHE_FILE
from the_front_office.clients.nba.types import (
    NineCatStats, 
    PlayerStats, 
    NBACacheData, 
    PlayerCacheRecord, 
    ScheduleCache, 
    GameRecord
)

logger = logging.getLogger(__name__)

# Cache TTLs
SCHEDULE_TTL_HOURS = 24
PLAYER_STATS_INVALIDATION_TIMES = [
    dt_time(1, 0),   # 1:00 AM PT (after games end)
    dt_time(15, 0),  # 3:00 PM PT (before games start)
]


class NBAClient:
    """
    Fetches NBA stats and schedule using nba_api with a unified local cache.

    Cache structure (.nba_cache.json):
    {
        "player_stats": {
            "<player_name>": {
                "stats": { "last_5": { ... }, ... },
                "updated_at": "<ISO timestamp>"
            }
        },
        "schedule": {
            "teams": { "<TRICODE>": [...], ... },
            "updated_at": "<ISO timestamp>"
        }
    }
    """
    def __init__(self) -> None:
        self._last_call_time: float = 0.0
        self._cache_file: Path = Path(NBA_CACHE_FILE)
        # Initialize with empty structure
        self._cache_data: NBACacheData = {
            "player_stats": {}, 
            "schedule": {"teams": {}, "updated_at": ""}
        }
        self._load_cache()

    # ── Cache I/O ──────────────────────────────────────────────────

    def _load_cache(self) -> None:
        """Load unified cache from disk."""
        if not self._cache_file.exists():
            return

        try:
            raw_data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            
            # Type-safe migration/validation
            player_stats = cast(dict[str, PlayerCacheRecord], raw_data.get("player_stats", {}))
            schedule = cast(ScheduleCache, raw_data.get("schedule", {"teams": {}, "updated_at": ""}))
            
            self._cache_data = {
                "player_stats": player_stats,
                "schedule": schedule
            }
            
            logger.debug(f"Loaded NBA cache: {len(self._cache_data['player_stats'])} players, "
                         f"schedule is {self._get_schedule_age_hours():.1f}h old.")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}. Starting fresh.")
            self._cache_data = {
                "player_stats": {}, 
                "schedule": {"teams": {}, "updated_at": ""}
            }

    def _save_cache(self) -> None:
        """Persist unified cache to disk."""
        try:
            self._cache_file.write_text(json.dumps(self._cache_data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def _get_schedule_age_hours(self) -> float:
        """Get age of cached schedule in hours."""
        updated_at = self._cache_data["schedule"].get("updated_at")
        if not updated_at:
            return 999.0
        try:
            ts = datetime.fromisoformat(updated_at)
            return (datetime.now() - ts).total_seconds() / 3600
        except ValueError:
            return 999.0

    def _is_player_stats_stale(self, updated_at_str: str) -> bool:
        """Check if a player's stats record has crossed an invalidation boundary (1AM/3PM PT)."""
        try:
            updated_at = datetime.fromisoformat(updated_at_str)
        except ValueError:
            return True

        now = datetime.now()
        # If record is from a previous day, it's definitely stale relative to today's 1AM/3PM
        if updated_at.date() < now.date():
            return True
        
        # If updated today, check if we crossed a boundary since the update
        for boundary_time in PLAYER_STATS_INVALIDATION_TIMES:
            boundary_dt = datetime.combine(now.date(), boundary_time)
            if updated_at < boundary_dt <= now:
                return True
        return False

    # ── Rate Limiting ──────────────────────────────────────────────

    def _wait_for_rate_limit(self) -> None:
        """Ensures at least NBA_API_DELAY seconds between calls."""
        elapsed = time.time() - self._last_call_time
        if elapsed < NBA_API_DELAY:
            time.sleep(NBA_API_DELAY - elapsed)
        self._last_call_time = time.time()

    # ── Player Stats ───────────────────────────────────────────────

    def _extract_9cat(self, row: "pd.Series[float]") -> NineCatStats:
        """Extract 9-cat stats from a pandas Series."""
        return NineCatStats(
            PTS=round(float(row.get('PTS', 0)), 1),
            REB=round(float(row.get('REB', 0)), 1),
            AST=round(float(row.get('AST', 0)), 1),
            STL=round(float(row.get('STL', 0)), 1),
            BLK=round(float(row.get('BLK', 0)), 1),
            TOV=round(float(row.get('TOV', 0)), 1),
            FG3M=round(float(row.get('FG3M', 0)), 1),
            FG_PCT=round(float(row.get('FG_PCT', 0)), 3),
            FT_PCT=round(float(row.get('FT_PCT', 0)), 3),
        )

    def get_player_stats(self, full_name: str, retries: int = 2) -> Optional[PlayerStats]:
        """Fetch recent stats (L5/L10/L15) for a player with per-record caching."""
        record = self._cache_data["player_stats"].get(full_name)
        if record and not self._is_player_stats_stale(record["updated_at"]):
            logger.debug(f"Cache hit for {full_name}")
            return record["stats"]

        for attempt in range(retries + 1):
            try:
                player_matches = players.find_players_by_full_name(full_name)
                if not player_matches:
                    return None

                player_id: int = player_matches[0]['id']
                stats_dict: PlayerStats = PlayerStats()
                
                self._wait_for_rate_limit()
                gamelog = playergamelog.PlayerGameLog(player_id=player_id)
                gamelog_df: pd.DataFrame = gamelog.get_data_frames()[0]

                if not gamelog_df.empty:
                    for count in [5, 10, 15]:
                        if len(gamelog_df) >= count:
                            stats_dict[f"last_{count}"] = self._extract_9cat(  # type: ignore[literal-required]
                                gamelog_df.head(count).mean(numeric_only=True)
                            )

                self._cache_data["player_stats"][full_name] = {
                    "stats": stats_dict,
                    "updated_at": datetime.now().isoformat()
                }
                self._save_cache()
                return stats_dict

            except Exception as e:
                if attempt < retries:
                    logger.warning(f"Retry {attempt+1}/{retries} for {full_name}: {e}")
                    time.sleep(2)
                    continue
                logger.warning(f"Failed to fetch stats for {full_name}: {e}")
        return None

    # ── Schedule ───────────────────────────────────────────────────

    def _ensure_schedule_loaded(self) -> None:
        """Fetch full season schedule via nba_api if stale or missing."""
        if self._cache_data["schedule"]["updated_at"] and self._get_schedule_age_hours() < SCHEDULE_TTL_HOURS:
            return

        logger.debug("Refreshing NBA schedule via nba_api...")
        try:
            self._wait_for_rate_limit()
            sched = scheduleleaguev2.ScheduleLeagueV2()
            data = sched.get_dict()

            team_games: Dict[str, list[GameRecord]] = {}
            for game_date_obj in data["leagueSchedule"]["gameDates"]:
                for game in game_date_obj["games"]:
                    game_info: GameRecord = {
                        "date": str(game["gameDateEst"])[:10],
                        "status": int(game["gameStatus"]),
                        "home": str(game["homeTeam"]["teamTricode"]),
                        "away": str(game["awayTeam"]["teamTricode"]),
                    }
                    team_games.setdefault(game_info["home"], []).append(game_info)
                    team_games.setdefault(game_info["away"], []).append(game_info)

            self._cache_data["schedule"] = {
                "teams": team_games,
                "updated_at": datetime.now().isoformat()
            }
            self._save_cache()
        except Exception as e:
            logger.warning(f"Failed to fetch NBA schedule: {e}")

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date) -> int:
        """Count scheduled/live games for a team in a date range."""
        self._ensure_schedule_loaded()
        games = self._cache_data["schedule"]["teams"].get(team_abbr.upper(), [])
        count = 0
        today = date.today()
        for g in games:
            game_date = date.fromisoformat(g["date"])
            if start_date <= game_date <= end_date and game_date >= today:
                if g["status"] in (1, 2):
                    count += 1
        return count

    def get_remaining_games_bulk(self, team_abbrs: list[str], start_date: date, end_date: date) -> Dict[str, int]:
        """Bulk count remaining games."""
        self._ensure_schedule_loaded()
        return {abbr.upper(): self.get_remaining_games(abbr, start_date, end_date) for abbr in set(team_abbrs)}
