from datetime import date

from yahoofantasy import Player  # type: ignore[import-untyped]

from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.nba.types import NineCatStats, PlayerStats


class PlayerContextBuilder:
    """
    Service to build rich context strings for players (rostered or free agents)
    by combining Yahoo data with NBA stats and schedule info.
    """

    def __init__(self, nba_client: NBAClient):
        self.nba = nba_client

    def _format_stats(self, stats_dict: PlayerStats) -> str:
        """Format recent trend stats into a readable string."""
        if not stats_dict:
            return "No stats available"

        parts: list[str] = []
        for key, label in [("last_5", "L5"), ("last_10", "L10"), ("last_15", "L15")]:
            if key in stats_dict:
                s: NineCatStats = stats_dict[key]  # type: ignore[literal-required]
                parts.append(
                    f"{label}: {s['PTS']}p {s['REB']}r {s['AST']}a {s['STL']}s {s['BLK']}b {s['TOV']}to {s['FG3M']}3pm FG{s['FG_PCT']:.1%} FT{s['FT_PCT']:.1%}"
                )

        return " | ".join(parts) if parts else "No recent stats"

    def get_remaining_games(self, team_abbr: str, matchup_start: date | None, matchup_end: date | None) -> int | None:
        """Get remaining games for a player's team in the matchup period."""
        if not matchup_start or not matchup_end:
            return None
        return self.nba.get_remaining_games(team_abbr, matchup_start, matchup_end)

    def build_context_for_players(
        self,
        players: list[Player],
        matchup_start: date | None = None,
        matchup_end: date | None = None,
        annotations: dict[str, str] | None = None,
        remaining_games: dict[str, int] | None = None,
    ) -> str:
        """
        Build a context string for a list of players.

        Args:
            players: List of Yahoo Player objects
            matchup_start: Start date of matchup (for schedule calculation)
            matchup_end: End date of matchup
            annotations: Optional map of player_key -> extra text (e.g. "Top in: PTS")
        """
        return "".join(
            self.build_player_lines(players, matchup_start, matchup_end, annotations, remaining_games).values()
        )

    def build_player_lines(
        self,
        players: list[Player],
        matchup_start: date | None = None,
        matchup_end: date | None = None,
        annotations: dict[str, str] | None = None,
        remaining_games: dict[str, int] | None = None,
    ) -> dict[str, str]:
        """Same as build_context_for_players, keyed by player name.

        Lets a caller keep only the lines it needs — the follow-up briefing
        carries the recommended free agents rather than all thirty.
        """
        if not players:
            return {}

        remaining_games = remaining_games or {}
        if not remaining_games and matchup_start and matchup_end:
            teams = [p.editorial_team_abbr for p in players]
            remaining_games = self.nba.get_remaining_games_bulk(teams, matchup_start, matchup_end)

        lines: dict[str, str] = {}
        for p in players:
            # Stats
            stats_dict = self.nba.get_player_stats(p.name.full)

            # Schedule
            games_left = remaining_games.get(p.editorial_team_abbr.upper(), None)
            games_str = f" [{games_left}G left]" if games_left is not None else ""

            # Status
            status = getattr(p, "status", None)
            injury_note = getattr(p, "injury_note", None)
            status_str = ""
            if status:
                status_str = f" [{status}]"
                if injury_note:
                    status_str += f" ({injury_note})"

            # IL Spot check for rostered players
            il_str = ""
            if hasattr(p, "selected_position") and getattr(p.selected_position, "position", "") in ("IL", "IL+"):
                il_str = " [IN IL SPOT]"

            # Annotation
            note = ""
            if annotations and p.player_key in annotations:
                note = f" {annotations[p.player_key]}"

            line = f"- {p.name.full} ({p.display_position}){il_str}{status_str}{games_str}{note}"
            if stats_dict:
                line += f": {self._format_stats(stats_dict)}"
            lines[p.name.full] = line + "\n"

        return lines
