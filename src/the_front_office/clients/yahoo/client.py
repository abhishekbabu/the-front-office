"""
Yahoo Fantasy Data Client.
"""
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional
from yahoofantasy import Player, League, Team, Week, Context
from yahoofantasy.api.parse import as_list, from_response_object
from the_front_office.config.settings import (
    YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, YAHOO_REDIRECT_URI, YAHOO_TOKEN_FILE
)
from the_front_office.clients.yahoo.types import PlayerStatus, PlayerStat, Timeframe, PlayerPosition
from the_front_office.clients.yahoo.constants import STAT_CATEGORIES, SCOUT_CATEGORIES

logger = logging.getLogger(__name__)

class YahooFantasyClient:
    @staticmethod
    def _token_exists() -> bool:
        """Check whether a cached OAuth2 token file already exists."""
        return Path(YAHOO_TOKEN_FILE).exists()

    @classmethod
    def login(cls, force: bool = False) -> None:
        """Run the yahoofantasy OAuth2 login flow."""
        if cls._token_exists() and not force:
            return

        print("🔐 Starting Yahoo Fantasy OAuth2 login …")
        print(f"   Redirect URI → {YAHOO_REDIRECT_URI}")
        print("   A browser window will open — please authorize the app.\n")

        # These should always be set due to .env loading in settings.py
        if not YAHOO_CLIENT_ID or not YAHOO_CLIENT_SECRET:
            print("⚠️  YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET must be set in .env")
            sys.exit(1)

        # Find the yahoofantasy executable
        python_dir = Path(sys.executable).parent
        yahoofantasy_bin_path = python_dir / "yahoofantasy.exe"
        yahoofantasy_bin = str(yahoofantasy_bin_path) if yahoofantasy_bin_path.exists() else "yahoofantasy"

        cmd = [
            yahoofantasy_bin,
            "login",
            "--redirect-uri", YAHOO_REDIRECT_URI,
            "--client-id", YAHOO_CLIENT_ID,
            "--client-secret", YAHOO_CLIENT_SECRET,
            "--listen-port", "8080",
        ]

        try:
            subprocess.run(cmd, check=True)
            print("\n✅ Login successful! Token saved.")
        except subprocess.CalledProcessError as exc:
            print(f"\n❌ Login failed (exit code {exc.returncode}).")
            sys.exit(1)

    @classmethod
    def get_context(cls) -> Context:
        """Return an authenticated yahoofantasy Context."""
        if not cls._token_exists():
            cls.login()
        return Context()

    def __init__(self, league: League):
        self.league = league

    def fetch_players(
        self,
        count: int = 25,
        status: PlayerStatus = PlayerStatus.ALL_AVAILABLE,
        sort: Optional[PlayerStat] = None,
        sort_type: Optional[Timeframe] = None,
        position: Optional[PlayerPosition] = None,
        **extra_params: str,
    ) -> List[Player]:
        """
        Fetch players from the Yahoo Fantasy API.

        This is the single entry point for all player queries. It builds
        the API query string directly, bypassing the yahoofantasy library's
        limited ``league.players()`` method.

        Args:
            count: Max number of players to return.
            status: Player availability filter (default: ALL_AVAILABLE).
            sort: Sort field (e.g. PlayerStat.ACTUAL_RANK, PlayerStat.BLOCKS).
            sort_type: Time window for sort (e.g. Timeframe.LAST_WEEK).
            position: Position filter (e.g. PlayerPosition.CENTER).
            **extra_params: Any additional Yahoo API query params.

        Returns:
            List of Player objects, up to ``count``.

        Examples:
            # Top available players by ownership %
            fetch_players(count=25)

            # Available point guards, sorted by fantasy points last week
            fetch_players(sort=PlayerStat.FANTASY_POINTS, sort_type=Timeframe.LAST_WEEK, position=PlayerPosition.POINT_GUARD)
        """
        # Build query params — enums serialize to their .value via str(Enum)
        params: Dict[str, str] = {"count": str(count), "status": status.value}
        if sort is not None:
            params["sort"] = sort.value
        if sort_type is not None:
            params["sort_type"] = sort_type.value
        if position is not None:
            params["position"] = position.value
        params.update(extra_params)

        # Build query string and cache key
        params_str = ";".join(f"{k}={v}" for k, v in params.items())
        query = f"players;{params_str}"
        cache_key = f"players_{self.league.id}_{'_'.join(params.values())}"

        logger.debug(f"Fetching players with query: {query}")

        try:
            data = self.league.ctx._load_or_fetch(cache_key, query, league=self.league.id)

            players_container = data["fantasy_content"]["league"]["players"]
            if not players_container or isinstance(players_container, str):
                return []

            players: List[Player] = []
            if "player" in players_container:
                for player_data in as_list(players_container["player"]):
                    p = Player(self.league)
                    from_response_object(p, player_data)
                    players.append(p)

            return players[:count]
        except Exception as e:
            logger.error(f"Error fetching players (query={query}): {e}")
            return []

    def fetch_top_by_stat(
        self,
        per_stat: int = 10,
        sort_type: Timeframe = Timeframe.LAST_WEEK,
    ) -> Dict[str, List[Player]]:
        """
        Fetch the top available players for each scoutable stat category.

        Iterates over SCOUT_STAT_IDS (all 9-cat stats except turnovers),
        making one API call per category.

        Args:
            per_stat: Number of players to fetch per stat category.
            sort_type: Time window for sorting (default: last week).

        Returns:
            Dict mapping stat display name → list of Player objects.
        """
        results: Dict[str, List[Player]] = {}
        for stat, stat_name in SCOUT_CATEGORIES.items():
            logger.debug(f"Fetching top {per_stat} players by {stat_name}...")
            players = self.fetch_players(
                count=per_stat,
                sort_type=sort_type,
                sort=stat,
            )
            results[stat_name] = players
        return results

    def get_user_team(self) -> Optional[Team]:
        """
        Identify the team owned by the current user.
        """
        for team in self.league.teams():
            if hasattr(team, "is_owned_by_current_login") and team.is_owned_by_current_login:
                return team
        return None

    def get_matchup_dates(self, my_team: Team) -> tuple[str, str]:
        """
        Get the start and end dates of the current matchup period.

        Returns:
            Tuple of (week_start, week_end) as ISO date strings (e.g. "2026-02-09").
            Returns ("", "") if matchup info is unavailable.
        """
        try:
            current_week = getattr(self.league, "current_week", None)
            if not current_week:
                return ("", "")

            week = Week(self.league.ctx, self.league, current_week)
            week.sync()

            for m in week.matchups:
                if m.team1.team_key == my_team.team_key or m.team2.team_key == my_team.team_key:
                    return (str(m.week_start), str(m.week_end))
            return ("", "")
        except Exception as e:
            logger.warning(f"Could not fetch matchup dates: {e}")
            return ("", "")

    def get_matchup_context(self, my_team: Team) -> str:
        """
        Fetch current week matchup, scores, and opponent roster.
        """
        try:
            current_week = getattr(self.league, "current_week", None)
            if not current_week:
                return ""
            
            week = Week(self.league.ctx, self.league, current_week)
            week.sync()
            
            my_matchup = None
            for m in week.matchups:
                if m.team1.team_key == my_team.team_key or m.team2.team_key == my_team.team_key:
                    my_matchup = m
                    break
            
            if not my_matchup:
                return ""

            is_team1 = my_matchup.team1.team_key == my_team.team_key
            opponent = my_matchup.team2 if is_team1 else my_matchup.team1
            
            # Scores & Stats
            teams_data = as_list(my_matchup.teams.team)
            my_data = teams_data[0] if is_team1 else teams_data[1]
            opp_data = teams_data[1] if is_team1 else teams_data[0]
            
            # Build Category Breakdown
            def get_stats(team_stats_obj):
                stats_list = as_list(team_stats_obj.stats.stat)
                return {str(s.stat_id): s.value for s in stats_list}

            my_stats = get_stats(my_data.team_stats)
            opp_stats = get_stats(opp_data.team_stats)
            
            breakdown = "\nCATEGORY BREAKDOWN (Us vs Opponent):"
            for stat, cat_name in STAT_CATEGORIES.items():
                val1 = my_stats.get(stat.value, "N/A")
                val2 = opp_stats.get(stat.value, "N/A")
                breakdown += f"\n- {cat_name}: {val1} vs {val2}"
            
            # Opponent Roster
            opp_roster: List[Player] = opponent.players()
            opp_roster_str = ", ".join([f"{p.name.full} ({p.display_position})" for p in opp_roster[:12]])
            
            context = f"\nCURRENT MATCHUP: Playing against {opponent.name}"
            context += f"\nMATCHUP SCORE: You {my_data.team_points.total} - {opp_data.team_points.total} Opponent"
            context += breakdown
            context += f"\nOPPONENT KEY PLAYERS: {opp_roster_str}"
            
            return context
        except Exception as e:
            logger.warning(f"Could not fetch matchup context: {e}")
            return ""

    def search_players(self, query: str) -> List[Player]:
        """
        Search for players by name using the league context.
        Uses league/{id}/players;search={query}
        """
        try:
            # Construct league-specific search query
            # league/{league_key}/players;search={query}
            league_key = self.league.league_key
            query_str = f"league/{league_key}/players;search={query}"
            cache_key = f"player_search_{league_key}_{query}"
            
            logger.debug(f"Searching players in league: {query_str}")
            
            # _load_or_fetch expects the relative URL part
            data = self.league.ctx._load_or_fetch(cache_key, query_str)
            
            # Navigate response structure:
            # fantasy_content -> league -> players -> player
            try:
                base = data["fantasy_content"]["league"]
                players_container = base.get("players", {})
            except KeyError:
                logger.warning(f"Unexpected response structure for search '{query}'")
                return []

            if not players_container or isinstance(players_container, str):
                return []

            results: List[Player] = []
            if "player" in players_container:
                for player_data in as_list(players_container["player"]):
                    # Create player bound to this league/context
                    p = Player(self.league) 
                    from_response_object(p, player_data)
                    results.append(p)
            
            return results

        except Exception as e:
            logger.error(f"Error searching for player '{query}': {e}")
            return []
