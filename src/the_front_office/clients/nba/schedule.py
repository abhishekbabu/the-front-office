"""
NBA Schedule Client — Fetches and caches the NBA season schedule from NBA.com CDN.
"""
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Dict
import urllib.request

from the_front_office.config.settings import NBA_SCHEDULE_CACHE_FILE

logger = logging.getLogger(__name__)

NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
CACHE_MAX_AGE_HOURS = 24


class NBAScheduleClient:
    """
    Fetches the full NBA season schedule from the NBA CDN and caches it locally.
    Provides methods to count remaining (unplayed) games for a team within a date range.
    """

    def __init__(self) -> None:
        self._cache_file = Path(NBA_SCHEDULE_CACHE_FILE)
        self._schedule: Dict[str, list[dict[str, object]]] = {}  # team_tricode → [game dicts]
        self._load_schedule()

    def _load_schedule(self) -> None:
        """Load schedule from cache if fresh, otherwise fetch from CDN."""
        if self._cache_file.exists():
            try:
                raw = json.loads(self._cache_file.read_text(encoding="utf-8"))
                cached_at = datetime.fromisoformat(raw["cached_at"])
                age_hours = (datetime.now() - cached_at).total_seconds() / 3600
                if age_hours < CACHE_MAX_AGE_HOURS:
                    self._schedule = raw["teams"]
                    logger.debug(f"Loaded schedule cache ({len(self._schedule)} teams, {age_hours:.1f}h old)")
                    return
                else:
                    logger.debug("Schedule cache is stale, refreshing...")
            except Exception as e:
                logger.debug(f"Could not load schedule cache: {e}")

        self._fetch_and_cache()

    def _fetch_and_cache(self) -> None:
        """Fetch schedule from NBA CDN and build a team-indexed lookup."""
        logger.debug("Fetching NBA schedule from CDN...")
        try:
            req = urllib.request.Request(NBA_SCHEDULE_URL, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # Build team → games index
            teams: Dict[str, list[dict[str, object]]] = {}
            for game_date_obj in data["leagueSchedule"]["gameDates"]:
                for game in game_date_obj["games"]:
                    game_info: dict[str, object] = {
                        "date": str(game["gameDateEst"])[:10],  # "2025-10-02"
                        "status": int(game["gameStatus"]),  # 1=scheduled, 2=live, 3=final
                        "home": str(game["homeTeam"]["teamTricode"]),
                        "away": str(game["awayTeam"]["teamTricode"]),
                    }
                    home_tri = str(game["homeTeam"]["teamTricode"])
                    away_tri = str(game["awayTeam"]["teamTricode"])
                    teams.setdefault(home_tri, []).append(game_info)
                    teams.setdefault(away_tri, []).append(game_info)

            self._schedule = teams

            # Cache to disk
            cache_data = {
                "cached_at": datetime.now().isoformat(),
                "teams": teams,
            }
            self._cache_file.write_text(json.dumps(cache_data), encoding="utf-8")
            logger.debug(f"Cached NBA schedule ({len(teams)} teams)")

        except Exception as e:
            logger.warning(f"Failed to fetch NBA schedule: {e}")
            self._schedule = {}

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date) -> int:
        """
        Count remaining (unplayed) games for a team within a date range.

        Args:
            team_abbr: NBA team tricode (e.g. "LAL", "PHI")
            start_date: Start of matchup period (inclusive)
            end_date: End of matchup period (inclusive)

        Returns:
            Number of games with status 1 (scheduled) in the date range.
        """
        games = self._schedule.get(team_abbr.upper(), [])
        count = 0
        today = date.today()
        for g in games:
            game_date = date.fromisoformat(str(g["date"]))
            if start_date <= game_date <= end_date and game_date >= today:
                # Status 1 = scheduled, or today's games that haven't finished
                status = int(str(g["status"]))
                if status in (1, 2):  # scheduled or in-progress
                    count += 1
        return count

    def get_remaining_games_bulk(
        self, team_abbrs: list[str], start_date: date, end_date: date
    ) -> Dict[str, int]:
        """
        Count remaining games for multiple teams at once.

        Returns:
            Dict mapping team tricode → remaining game count.
        """
        result: Dict[str, int] = {}
        for abbr in set(team_abbrs):
            result[abbr.upper()] = self.get_remaining_games(abbr, start_date, end_date)
        return result
