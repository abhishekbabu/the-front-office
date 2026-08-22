"""
Yahoo Fantasy Data Client.
"""

import logging
import subprocess
import sys
from pathlib import Path

from yahoofantasy import Context, League, Player, Team, Week
from yahoofantasy.api.parse import as_list, from_response_object

from the_front_office.clients.yahoo.constants import SCOUT_CATEGORIES, STAT_CATEGORIES
from the_front_office.clients.yahoo.types import PlayerPosition, PlayerStat, PlayerStatus, Timeframe
from the_front_office.config.settings import settings

logger = logging.getLogger(__name__)


class YahooFantasyClient:
    @staticmethod
    def _token_exists() -> bool:
        """Check whether a cached OAuth2 token file already exists."""
        return Path(settings.yahoo_token_file).exists()

    @classmethod
    def login(cls, force: bool = False) -> None:
        """Run the yahoofantasy OAuth2 login flow."""
        if cls._token_exists() and not force:
            return

        print("🔐 Starting Yahoo Fantasy OAuth2 login …")
        print(f"   Redirect URI → {settings.yahoo_redirect_uri}")
        print("   A browser window will open — please authorize the app.\n")

        # Bound locally so the type checker can see them narrowed to str.
        client_id, client_secret = settings.yahoo_client_id, settings.yahoo_client_secret
        if not client_id or not client_secret:
            print("⚠️  YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET must be set in .env")
            sys.exit(1)

        # Find the yahoofantasy executable
        python_dir = Path(sys.executable).parent
        yahoofantasy_bin_path = python_dir / "yahoofantasy.exe"
        yahoofantasy_bin = str(yahoofantasy_bin_path) if yahoofantasy_bin_path.exists() else "yahoofantasy"

        cmd = [
            yahoofantasy_bin,
            "login",
            "--redirect-uri",
            settings.yahoo_redirect_uri,
            "--client-id",
            client_id,
            "--client-secret",
            client_secret,
            "--listen-port",
            "8080",
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
        sort: PlayerStat | None = None,
        sort_type: Timeframe | None = None,
        position: PlayerPosition | None = None,
        **extra_params: str,
    ) -> list[Player]:
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
        params: dict[str, str] = {"count": str(count), "status": status.value}
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

            players: list[Player] = []
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
    ) -> dict[str, list[Player]]:
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
        results: dict[str, list[Player]] = {}
        for stat, stat_name in SCOUT_CATEGORIES.items():
            logger.debug(f"Fetching top {per_stat} players by {stat_name}...")
            players = self.fetch_players(
                count=per_stat,
                sort_type=sort_type,
                sort=stat,
            )
            results[stat_name] = players
        return results

    def get_user_team(self) -> Team | None:
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
            opp_roster: list[Player] = opponent.players()
            opp_roster_str = ", ".join([f"{p.name.full} ({p.display_position})" for p in opp_roster[:12]])

            context = f"\nCURRENT MATCHUP: Playing against {opponent.name}"
            context += f"\nMATCHUP SCORE: You {my_data.team_points.total} - {opp_data.team_points.total} Opponent"
            context += breakdown
            context += f"\nOPPONENT KEY PLAYERS: {opp_roster_str}"

            return context
        except Exception as e:
            logger.warning(f"Could not fetch matchup context: {e}")
            return ""

    def search_players(self, query: str) -> list[Player]:
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

            results: list[Player] = []
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
