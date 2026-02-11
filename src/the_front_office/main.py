"""
main.py — Entry point for The Front Office.

Authenticates with Yahoo Fantasy, fetches your NBA leagues,
and prints your current roster to the terminal.
"""

import sys
from datetime import datetime

from the_front_office.auth import login, get_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_header(text: str) -> None:
    """Print a styled section header."""
    width = 60
    print("\n" + "═" * width)
    print(f"  {text}")
    print("═" * width)


def _print_roster(team) -> None:
    """Pretty-print a team's roster."""
    players = team.players()
    if not players:
        print("  (no players found)")
        return

    print(f"  {'Player':<30} {'Position':<10} {'Team':<6}")
    print(f"  {'─' * 30} {'─' * 10} {'─' * 6}")
    for player in players:
        name = player.name.full
        position = player.display_position
        nba_team = player.editorial_team_abbr
        print(f"  {name:<30} {position:<10} {nba_team:<6}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Authenticate and print the current NBA fantasy roster."""

    _print_header("🏀 The Front Office — NBA Fantasy Intelligence")
    print(f"  {datetime.now().strftime('%A, %B %d %Y  •  %I:%M %p')}")

    # --- Auth ---
    login()
    ctx = get_context()

    # --- Fetch NBA leagues for the current season ---
    # NBA seasons are identified by their start year (e.g., 2025-26 is '2025')
    now = datetime.now()
    # If we are in Jan-Aug, the current season started in the previous year
    season_year = now.year if now.month >= 9 else now.year - 1
    
    print(f"\n  Fetching NBA leagues for {season_year} season …")

    leagues = ctx.get_leagues("nba", season_year)

    if not leagues:
        print("  ⚠️  No NBA leagues found for this season.")
        sys.exit(0)

    # --- Print each league's roster ---
    for league in leagues:
        _print_header(f"League: {league.name}")
        print(f"  ID: {league.id}  •  Type: {league.league_type}\n")

        for team in league.teams():
            is_mine = "(YOU)" if hasattr(team, "is_owned_by_current_login") and team.is_owned_by_current_login else ""
            print(f"\n  📋 {team.name} — managed by {team.manager.nickname} {is_mine}")
            _print_roster(team)

    _print_header("Done ✅")


if __name__ == "__main__":
    main()
