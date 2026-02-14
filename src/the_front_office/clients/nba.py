"""
NBA.com Data Client (via nba_api).
"""
import time
import logging
from typing import Optional
from nba_api.stats.static import players, teams  # type: ignore[import-untyped]
from nba_api.stats.endpoints import playercareerstats, playerdashboardbygeneralsplits  # type: ignore[import-untyped]
from the_front_office.config.settings import NBA_API_DELAY

logger = logging.getLogger(__name__)

class NBAClient:
    """
    Fetches real-world NBA stats using the nba_api library.
    """
    def __init__(self):
        self._last_call_time = 0.0

    def _wait_for_rate_limit(self):
        """Ensures at least NBA_API_DELAY seconds between calls."""
        elapsed = time.time() - self._last_call_time
        if elapsed < NBA_API_DELAY:
            time.sleep(NBA_API_DELAY - elapsed)
        self._last_call_time = time.time()

    def get_player_stats(self, full_name: str, retries: int = 2) -> Optional[str]:
        """
        Fetch season averages and recent trends for a player with retries.
        """
        for attempt in range(retries + 1):
            try:
                # 1. Find Player ID
                player_matches = players.find_players_by_full_name(full_name)
                if not player_matches:
                    return None
                
                player_id = player_matches[0]['id']
                
                # 2. Fetch Season Averages
                self._wait_for_rate_limit()
                career = playercareerstats.PlayerCareerStats(player_id=player_id)
                career_df = career.get_data_frames()[0]
                
                # Get latest season row
                if career_df.empty:
                    return None
                
                latest_season = career_df.iloc[-1]
                avg_stats = f"Season: {latest_season['PTS']} PTS, {latest_season['REB']} REB, {latest_season['AST']} AST"

                # 3. Fetch Recent Trends (Last 5 Games)
                self._wait_for_rate_limit()
                splits = playerdashboardbygeneralsplits.PlayerDashboardByGeneralSplits(
                    player_id=player_id, 
                    last_n_games=5
                )
                splits_df = splits.get_data_frames()[0]
                
                if not splits_df.empty:
                    recent = splits_df.iloc[0]
                    avg_stats += f" | L5: {recent['PTS']} PTS, {recent['REB']} REB, {recent['AST']} AST"

                return avg_stats

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
