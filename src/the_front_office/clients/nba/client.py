"""
NBA.com Data Client (via nba_api).
"""
import time
import json
import logging
from pathlib import Path
from datetime import datetime, time as dt_time
from typing import Optional, Dict
import pandas as pd
from nba_api.stats.static import players, teams  # type: ignore[import-untyped]
from nba_api.stats.endpoints import playergamelog  # type: ignore[import-untyped]
from the_front_office.config.settings import NBA_API_DELAY, NBA_STATS_CACHE_FILE
from the_front_office.clients.nba.types import NineCatStats, PlayerStats

logger = logging.getLogger(__name__)

class NBAClient:
    """
    Fetches real-world NBA stats using the nba_api library with local caching.
    """
    def __init__(self) -> None:
        self._last_call_time: float = 0.0
        self._cache: Dict[str, PlayerStats] = {}
        self._cache_file: Path = Path(NBA_STATS_CACHE_FILE)
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cache from JSON file if it exists and is valid."""
        if not self._cache_file.exists():
            logger.debug("No cache file found. Starting fresh.")
            return
        
        try:
            with open(self._cache_file, 'r') as f:
                self._cache = json.load(f)
            
            # Check if cache should be invalidated
            if not self._is_cache_valid():
                logger.debug("Cache is stale. Clearing cache.")
                self._cache = {}
                self._save_cache()
            else:
                logger.debug(f"Loaded {len(self._cache)} cached player stats.")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}. Starting fresh.")
            self._cache = {}

    def _save_cache(self) -> None:
        """Save cache to JSON file."""
        try:
            with open(self._cache_file, 'w') as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def _is_cache_valid(self) -> bool:
        """
        Check if cache should be invalidated based on time.
        Cache invalidates twice daily:
        - 3:00 PM PT (before games start)
        - 1:00 AM PT (after games end)
        """
        if not self._cache:
            return True  # Empty cache is always valid
        
        now = datetime.now()
        
        # Define invalidation times (Pacific Time assumed)
        invalidation_times = [
            dt_time(15, 0),  # 3:00 PM PT
            dt_time(1, 0),   # 1:00 AM PT
        ]
        
        # Check if we've crossed an invalidation boundary since last cache write
        # For simplicity, we'll invalidate if current hour matches invalidation hours
        current_hour = now.time().hour
        if current_hour in [t.hour for t in invalidation_times]:
            # Check if cache was written before this invalidation window
            cache_mtime = datetime.fromtimestamp(self._cache_file.stat().st_mtime)
            if cache_mtime.hour != current_hour:
                return False  # Cache is stale
        
        return True

    def _wait_for_rate_limit(self) -> None:
        """Ensures at least NBA_API_DELAY seconds between calls."""
        elapsed = time.time() - self._last_call_time
        if elapsed < NBA_API_DELAY:
            time.sleep(NBA_API_DELAY - elapsed)
        self._last_call_time = time.time()

    def _extract_9cat(self, row: "pd.Series[float]") -> NineCatStats:
        """Extract 9-cat stats from a pandas Series (row or aggregated mean)."""
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
        """
        Fetch recent stats for a player with caching and retries.
        Uses 1 API call (game log) to compute L5/L10/L15 splits.
        """
        # Check cache first
        if full_name in self._cache:
            logger.debug(f"Cache hit for {full_name}")
            return self._cache[full_name]
        
        # Cache miss - fetch from API
        for attempt in range(retries + 1):
            try:
                # 1. Find Player ID
                player_matches = players.find_players_by_full_name(full_name)
                if not player_matches:
                    return None
                
                player_id: int = player_matches[0]['id']
                
                # 2. Fetch Game Log (1 API call)
                stats_dict: PlayerStats = PlayerStats()
                
                self._wait_for_rate_limit()
                gamelog = playergamelog.PlayerGameLog(player_id=player_id)
                gamelog_df: pd.DataFrame = gamelog.get_data_frames()[0]
                
                if not gamelog_df.empty:
                    if len(gamelog_df) >= 5:
                        stats_dict["last_5"] = self._extract_9cat(
                            gamelog_df.head(5).mean(numeric_only=True)
                        )
                    if len(gamelog_df) >= 10:
                        stats_dict["last_10"] = self._extract_9cat(
                            gamelog_df.head(10).mean(numeric_only=True)
                        )
                    if len(gamelog_df) >= 15:
                        stats_dict["last_15"] = self._extract_9cat(
                            gamelog_df.head(15).mean(numeric_only=True)
                        )

                # Cache the result
                self._cache[full_name] = stats_dict
                self._save_cache()
                
                return stats_dict

            except Exception as e:
                if attempt < retries:
                    logger.warning(f"Retry {attempt+1}/{retries} for {full_name} after error: {e}")
                    time.sleep(2) # Extra wait on error
                    continue
                logger.warning(f"Failed to fetch NBA stats for {full_name} after {retries} retries: {e}")
                return None
        return None

    def get_team_stats(self, team_name: str) -> Optional[str]:
        """
        Fetch basic team stats/standing info (Simplified for now).
        """
        try:
            team_matches = teams.find_teams_by_full_name(team_name)
            if not team_matches:
                return None
            
            # For now, just return the team abbreviation/full name as context
            team = team_matches[0]
            return f"{team['full_name']} ({team['abbreviation']})"
        except Exception as e:
            logger.warning(f"Could not fetch team stats for {team_name}: {e}")
            return None
