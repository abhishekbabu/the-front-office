from typing import List, Optional, Dict
from datetime import date
from yahoofantasy import Player # type: ignore[import-untyped]
from the_front_office.clients.nba.client import NBAClient
from the_front_office.clients.nba.types import PlayerStats, NineCatStats

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
        
        parts: List[str] = []
        for key, label in [("last_5", "L5"), ("last_10", "L10"), ("last_15", "L15")]:
            if key in stats_dict:
                s: NineCatStats = stats_dict[key]  # type: ignore[literal-required]
                parts.append(f"{label}: {s['PTS']}p {s['REB']}r {s['AST']}a {s['STL']}s {s['BLK']}b {s['TOV']}to {s['FG3M']}3pm FG{s['FG_PCT']:.1%} FT{s['FT_PCT']:.1%}")
        
        return " | ".join(parts) if parts else "No recent stats"

    def get_remaining_games(
        self, team_abbr: str, matchup_start: Optional[date], matchup_end: Optional[date]
    ) -> Optional[int]:
        """Get remaining games for a player's team in the matchup period."""
        if not matchup_start or not matchup_end:
            return None
        return self.nba.get_remaining_games(team_abbr, matchup_start, matchup_end)

    def build_context_for_players(
        self, 
        players: List[Player], 
        matchup_start: Optional[date] = None, 
        matchup_end: Optional[date] = None,
        annotations: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Build a context string for a list of players.
        
        Args:
            players: List of Yahoo Player objects
            matchup_start: Start date of matchup (for schedule calculation)
            matchup_end: End date of matchup
            annotations: Optional map of player_key -> extra text (e.g. "Top in: PTS")
        """
        if not players:
            return ""

        # 1. Bulk fetch schedule
        remaining_games: Dict[str, int] = {}
        if matchup_start and matchup_end:
            teams = [p.editorial_team_abbr for p in players]
            remaining_games = self.nba.get_remaining_games_bulk(teams, matchup_start, matchup_end)

        # 2. Build string
        context_str = ""
        for p in players:
            # Stats
            stats_dict = self.nba.get_player_stats(p.name.full)
            
            # Schedule
            games_left = remaining_games.get(p.editorial_team_abbr.upper(), None)
            games_str = f" [{games_left}G left]" if games_left is not None else ""
            
            # Status
            status = getattr(p, 'status', None)
            injury_note = getattr(p, 'injury_note', None)
            status_str = ""
            if status:
                status_str = f" [{status}]"
                if injury_note:
                    status_str += f" ({injury_note})"
            
            # Annotation
            note = ""
            if annotations and p.player_key in annotations:
                note = f" {annotations[p.player_key]}"

            context_str += f"- {p.name.full} ({p.display_position}){status_str}{games_str}{note}"
            if stats_dict:
                context_str += f": {self._format_stats(stats_dict)}"
            context_str += "\n"
            
        return context_str
