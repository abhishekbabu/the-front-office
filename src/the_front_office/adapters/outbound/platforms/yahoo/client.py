"""Yahoo Fantasy league data: rosters, matchups and player queries."""

import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from yahoofantasy import Context, League, Player, Team, Week
from yahoofantasy.api.parse import as_list, from_response_object, parse_response

from the_front_office.adapters.outbound.platforms.yahoo.constants import SCOUT_CATEGORIES, STAT_CATEGORIES
from the_front_office.adapters.outbound.platforms.yahoo.types import (
    MatchupInfo,
    PlayerPosition,
    PlayerStat,
    PlayerStatus,
    Timeframe,
)
from the_front_office.config.settings import settings
from the_front_office.domain.errors import TeamNotFoundError, YahooAPIError

logger = logging.getLogger(__name__)

# yahoofantasy persists every response for an hour. That suits rosters, but the
# scoreboard drives the "which categories are close" analysis and goes stale
# within a game night.
SCOREBOARD_TTL_SECONDS = 120

# The eight category queries are independent; Yahoo tolerates this easily and it
# is the dominant latency in a scout run.
MAX_PARALLEL_YAHOO_REQUESTS = 8


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
        """Fetch players, building the Yahoo query string directly.

        The SDK's `league.players()` cannot sort by an individual stat over a
        time window, which is what free-agent discovery needs.

        Raises:
            YahooAPIError: the request failed. An empty list means no matches.
        """
        query, cache_key = self._player_query(count, status, sort, sort_type, position, **extra_params)
        logger.debug(f"Fetching players with query: {query}")

        try:
            data = self.league.ctx._load_or_fetch(cache_key, query, league=self.league.id)
            return self._parse_players(data, count)
        except Exception as e:
            logger.error(f"Error fetching players (query={query}): {e}")
            raise YahooAPIError(f"Yahoo player query failed ({query}): {e}") from e

    def _player_query(
        self,
        count: int,
        status: PlayerStatus,
        sort: PlayerStat | None,
        sort_type: Timeframe | None,
        position: PlayerPosition | None,
        **extra_params: str,
    ) -> tuple[str, str]:
        """Build the Yahoo query string and its persistence key."""
        params: dict[str, str] = {"count": str(count), "status": status.value}
        if sort is not None:
            params["sort"] = sort.value
        if sort_type is not None:
            params["sort_type"] = sort_type.value
        if position is not None:
            params["position"] = position.value
        params.update(extra_params)

        params_str = ";".join(f"{k}={v}" for k, v in params.items())
        return f"players;{params_str}", f"players_{self.league.id}_{'_'.join(params.values())}"

    def _parse_players(self, data: Any, count: int) -> list[Player]:
        """Walk a players response into Player objects."""
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

    def fetch_top_by_stat(
        self,
        per_stat: int = 10,
        sort_type: Timeframe = Timeframe.LAST_WEEK,
    ) -> dict[str, list[Player]]:
        """Top available players per scoutable category, keyed by category name.

        One request per category in SCOUT_CATEGORIES, run concurrently.
        """
        specs = {
            stat_name: self._player_query(per_stat, PlayerStatus.ALL_AVAILABLE, stat, sort_type, None)
            for stat, stat_name in SCOUT_CATEGORIES.items()
        }

        ctx = self.league.ctx
        cached: dict[str, Any] = {}
        misses: dict[str, tuple[str, str]] = {}
        for stat_name, (query, cache_key) in specs.items():
            raw = ctx._load(cache_key, default=None)
            if raw is None:
                misses[stat_name] = (query, cache_key)
            else:
                cached[stat_name] = raw

        fetched = self._fetch_raw_parallel(misses) if misses else {}

        results: dict[str, list[Player]] = {}
        for stat_name in specs:
            raw = cached.get(stat_name, fetched.get(stat_name))
            if raw is None:
                results[stat_name] = []
                continue
            try:
                results[stat_name] = self._parse_players(parse_response(raw), per_stat)
            except Exception as e:
                logger.error(f"Could not parse {stat_name} leaders: {e}")
                raise YahooAPIError(f"Yahoo returned an unreadable {stat_name} response: {e}") from e
        return results

    def _fetch_raw_parallel(self, misses: dict[str, tuple[str, str]]) -> dict[str, Any]:
        """Fetch several player queries concurrently, then persist them serially.

        Only the HTTP calls are parallel. yahoofantasy's persistence layer does a
        read-modify-write of one shared pickle file, so concurrent saves would
        clobber each other — the writes stay on this thread. A token refresh
        racing across threads is harmless (both get a valid token), but it is
        forced once up front rather than N times.
        """
        ctx = self.league.ctx
        # Refresh the token on this thread first. make_request would do it
        # lazily, but then every worker could trigger its own refresh.
        refresh = getattr(ctx, "_get_access_token", None)
        if refresh and not getattr(ctx, "_access_token", None):
            refresh()

        def _fetch(item: tuple[str, tuple[str, str]]) -> tuple[str, Any]:
            stat_name, (query, _) = item
            return stat_name, ctx.make_request(query, league=self.league.id)

        raw_by_stat: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=min(len(misses), MAX_PARALLEL_YAHOO_REQUESTS)) as pool:
            for stat_name, raw in pool.map(_fetch, misses.items()):
                raw_by_stat[stat_name] = raw

        # Serial: one writer, so the shared pickle cannot be clobbered.
        for stat_name, raw in raw_by_stat.items():
            try:
                parse_response(raw)  # only persist what parses, as _load_or_fetch does
                ctx._save(misses[stat_name][1], raw)
            except Exception as e:
                logger.warning(f"Not persisting unparseable {stat_name} response: {e}")
        return raw_by_stat

    def get_user_team(self) -> Team:
        """Identify the team owned by the current user.

        Raises:
            TeamNotFoundError: the login owns no team in this league.
        """
        for team in self.league.teams():
            if hasattr(team, "is_owned_by_current_login") and team.is_owned_by_current_login:
                return team
        raise TeamNotFoundError(self.league.name)

    def _sync_current_week(self) -> Week | None:
        """Fetch the current week's scoreboard, once and freshly.

        The SDK persists every response for an hour, which is far too long for
        the scoreboard the "which categories are close" analysis rests on.
        Pre-warming the same persistence key with a short TTL forces a refetch,
        and Week.sync then reads the value just refreshed.
        """
        current_week = getattr(self.league, "current_week", None)
        if not current_week:
            return None

        ctx = self.league.ctx
        try:
            ctx._load_or_fetch(
                f"weeks.{self.league.id}.{current_week}",
                f"scoreboard;week={current_week}",
                league=self.league.id,
                persist_ttl=SCOREBOARD_TTL_SECONDS,
            )
        except Exception as e:
            # A refresh failure is not fatal — Week.sync falls back to whatever
            # is persisted, which is stale but usable.
            logger.warning(f"Could not refresh scoreboard, using persisted copy: {e}")

        week = Week(ctx, self.league, current_week)
        week.sync()
        return week

    def _find_matchup(self, week: Week, my_team: Team) -> Any:
        for m in week.matchups:
            if my_team.team_key in (m.team1.team_key, m.team2.team_key):
                return m
        return None

    def get_matchup(self, my_team: Team) -> MatchupInfo:
        """Fetch the current matchup once, returning both context and dates."""
        try:
            week = self._sync_current_week()
            if week is None:
                return MatchupInfo()

            matchup = self._find_matchup(week, my_team)
            if matchup is None:
                return MatchupInfo()

            return MatchupInfo(
                context=self._render_matchup(matchup, my_team),
                week_start=str(matchup.week_start),
                week_end=str(matchup.week_end),
            )
        except Exception as e:
            logger.warning(f"Could not fetch matchup: {e}")
            return MatchupInfo()

    def _render_matchup(self, matchup: Any, my_team: Team) -> str:
        """Format a matchup into the context block used in AI prompts."""
        is_team1 = matchup.team1.team_key == my_team.team_key
        opponent = matchup.team2 if is_team1 else matchup.team1

        teams_data = as_list(matchup.teams.team)
        my_data = teams_data[0] if is_team1 else teams_data[1]
        opp_data = teams_data[1] if is_team1 else teams_data[0]

        def get_stats(team_stats_obj: Any) -> dict[str, Any]:
            return {str(s.stat_id): s.value for s in as_list(team_stats_obj.stats.stat)}

        my_stats = get_stats(my_data.team_stats)
        opp_stats = get_stats(opp_data.team_stats)

        breakdown = "\nCATEGORY BREAKDOWN (Us vs Opponent):"
        for stat, cat_name in STAT_CATEGORIES.items():
            breakdown += f"\n- {cat_name}: {my_stats.get(stat.value, 'N/A')} vs {opp_stats.get(stat.value, 'N/A')}"

        opp_roster: list[Player] = opponent.players()
        opp_roster_str = ", ".join(f"{p.name.full} ({p.display_position})" for p in opp_roster[:12])

        return (
            f"\nCURRENT MATCHUP: Playing against {opponent.name}"
            f"\nMATCHUP SCORE: You {my_data.team_points.total} - {opp_data.team_points.total} Opponent"
            f"{breakdown}"
            f"\nOPPONENT KEY PLAYERS: {opp_roster_str}"
        )

    def get_matchup_dates(self, my_team: Team) -> tuple[str, str]:
        """Start and end dates of the current matchup period, or ("", "")."""
        info = self.get_matchup(my_team)
        return (info.week_start, info.week_end)

    def get_matchup_context(self, my_team: Team) -> str:
        """Current matchup, scores and opponent roster as prompt context."""
        return self.get_matchup(my_team).context

    def search_players(self, query: str) -> list[Player]:
        """
        Search for players by name using the league context.
        Uses league/{id}/players;search={query}
        """
        try:
            league_key = self.league.league_key
            query_str = f"league/{league_key}/players;search={query}"
            cache_key = f"player_search_{league_key}_{query}"

            logger.debug(f"Searching players in league: {query_str}")

            data = self.league.ctx._load_or_fetch(cache_key, query_str)

            try:
                base = data["fantasy_content"]["league"]
                players_container = base.get("players", {})
            except KeyError as e:
                raise YahooAPIError(f"Unexpected Yahoo response structure for search {query!r}") from e

            if not players_container or isinstance(players_container, str):
                return []

            results: list[Player] = []
            if "player" in players_container:
                for player_data in as_list(players_container["player"]):
                    p = Player(self.league)
                    from_response_object(p, player_data)
                    results.append(p)

            return results

        except YahooAPIError:
            raise
        except Exception as e:
            logger.error(f"Error searching for player '{query}': {e}")
            raise YahooAPIError(f"Yahoo player search failed for {query!r}: {e}") from e
