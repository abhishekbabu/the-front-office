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
from nba_api.stats.endpoints import leaguegamelog, scheduleleaguev2  # type: ignore[import-untyped]
from the_front_office.config.settings import NBA_API_DELAY, NBA_CACHE_FILE
from the_front_office.clients.nba.types import (
    NineCatStats, 
    PlayerStats, 
    NBACacheData, 
    LeagueGamelogCache,
    GameLogRecord,
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
        "league_gamelog": {
            "games": { "<player_name>": [{ "GAME_DATE": ... }, ...] },
            "updated_at": "<ISO timestamp>"
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
            "league_gamelog": {"games": {}, "updated_at": ""}, 
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
            league_gamelog = cast(LeagueGamelogCache, raw_data.get("league_gamelog", {"games": {}, "updated_at": ""}))
            schedule = cast(ScheduleCache, raw_data.get("schedule", {"teams": {}, "updated_at": ""}))
            
            self._cache_data = {
                "league_gamelog": league_gamelog,
                "schedule": schedule
            }
            
            num_players = len(self._cache_data['league_gamelog']['games'])
            logger.debug(f"Loaded NBA cache: {num_players} players in gamelog, "
                         f"schedule is {self._get_schedule_age_hours():.1f}h old.")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}. Starting fresh.")
            self._cache_data = {
                "league_gamelog": {"games": {}, "updated_at": ""}, 
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

    def _is_league_gamelog_stale(self) -> bool:
        """Check if the league gamelog has crossed an invalidation boundary (1AM/3PM PT)."""
        updated_at_str = self._cache_data["league_gamelog"]["updated_at"]
        if not updated_at_str:
            return True
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

    def _ensure_league_gamelog_loaded(self, retries: int = 2) -> None:
        if not self._is_league_gamelog_stale():
            return

        logger.debug("Refreshing league gamelog via nba_api...")
        for attempt in range(retries + 1):
            try:
                self._wait_for_rate_limit()
                # Fetch full season gamelog for all players. Note that the standard timeout is much larger 
                # here as we are doing the entire DB table for the season.
                log = leaguegamelog.LeagueGameLog(player_or_team_abbreviation='P', timeout=60)
                df = log.get_data_frames()[0]
                
                games_by_player: dict[str, list[GameLogRecord]] = {}
                for row in df.itertuples(index=False):
                    player_name = row.PLAYER_NAME
                    record: GameLogRecord = {
                        "GAME_DATE": row.GAME_DATE,
                        "PTS": float(row.PTS),
                        "REB": float(row.REB),
                        "AST": float(row.AST),
                        "STL": float(row.STL),
                        "BLK": float(row.BLK),
                        "TOV": float(row.TOV),
                        "FG3M": float(row.FG3M),
                        "FGA": float(row.FGA),
                        "FGM": float(row.FGM),
                        "FTA": float(row.FTA),
                        "FTM": float(row.FTM)
                    }
                    if player_name not in games_by_player:
                        games_by_player[player_name] = []
                    games_by_player[player_name].append(record)
                
                self._cache_data["league_gamelog"] = {
                    "games": games_by_player,
                    "updated_at": datetime.now().isoformat()
                }
                self._save_cache()
                return
            except Exception as e:
                if attempt < retries:
                    backoff_time = 2 ** attempt * 5
                    logger.warning(f"Retry {attempt+1}/{retries} for league gamelog in {backoff_time}s: {e}")
                    time.sleep(backoff_time)
                    continue
                logger.warning(f"Failed to fetch league gamelog: {e}")

    def _extract_9cat_from_records(self, records: list[GameLogRecord]) -> NineCatStats:
        """Extract 9-cat stats from a list of structured game records."""
        df = pd.DataFrame(records)
        mean_vals = df.mean(numeric_only=True)
        # Accurately compute percentages instead of naive average
        fga_sum = df['FGA'].sum()
        fgm_sum = df['FGM'].sum()
        fta_sum = df['FTA'].sum()
        ftm_sum = df['FTM'].sum()
        
        fg_pct = (fgm_sum / fga_sum) if fga_sum > 0 else 0.0
        ft_pct = (ftm_sum / fta_sum) if fta_sum > 0 else 0.0

        return NineCatStats(
            PTS=round(float(mean_vals.get('PTS', 0)), 1),
            REB=round(float(mean_vals.get('REB', 0)), 1),
            AST=round(float(mean_vals.get('AST', 0)), 1),
            STL=round(float(mean_vals.get('STL', 0)), 1),
            BLK=round(float(mean_vals.get('BLK', 0)), 1),
            TOV=round(float(mean_vals.get('TOV', 0)), 1),
            FG3M=round(float(mean_vals.get('FG3M', 0)), 1),
            FG_PCT=round(float(fg_pct), 3),
            FT_PCT=round(float(ft_pct), 3),
        )

    def get_player_stats(self, full_name: str, retries: int = 2) -> Optional[PlayerStats]:
        """Fetch recent stats (L5/L10/L15) for a player using the cached league gamelog."""
        self._ensure_league_gamelog_loaded(retries)
        games = self._cache_data["league_gamelog"]["games"].get(full_name)
        
        if not games:
            # Player not found or has no games
            return None

        # Sort games descending by date
        games.sort(key=lambda g: g["GAME_DATE"], reverse=True)
        
        stats_dict: PlayerStats = PlayerStats()
        for count in [5, 10, 15]:
            if len(games) >= count:
                stats_dict[f"last_{count}"] = self._extract_9cat_from_records(games[:count])  # type: ignore[literal-required]

        return stats_dict if stats_dict else None

    # ── Schedule ───────────────────────────────────────────────────

    def _ensure_schedule_loaded(self) -> None:
        """Fetch full season schedule via nba_api if stale or missing."""
        if self._cache_data["schedule"]["updated_at"] and self._get_schedule_age_hours() < SCHEDULE_TTL_HOURS:
            return

        logger.debug("Refreshing NBA schedule via nba_api...")
        try:
            self._wait_for_rate_limit()
            sched = scheduleleaguev2.ScheduleLeagueV2(timeout=5)
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
