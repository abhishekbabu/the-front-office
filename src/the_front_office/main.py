"""
main.py — Entry point for The Front Office.

Authenticates with Yahoo Fantasy, fetches your NBA leagues,
and prints your current roster to the terminal.
"""

import sys
import argparse
from datetime import datetime
from typing import List

from the_front_office.clients.yahoo import YahooFantasyClient
from the_front_office.scout import Scout
from yahoofantasy import League, Team  # type: ignore[import-untyped]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_header(text: str) -> None:
    """Print a styled section header."""
    width = 60
    print("\n" + "═" * width)
    print(f"  {text}")
    print("═" * width)


def _print_roster(team: Team) -> None:
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
    """Authenticate and print the current NBA fantasy roster or run scout report."""
    parser = argparse.ArgumentParser(description="The Front Office — NBA Fantasy Intelligence")
    parser.add_argument("--scout", action="store_true", help="Run the Morning Scout Report (AI waiver analysis)")
    args = parser.parse_args()

    _print_header("🏀 The Front Office — NBA Fantasy Intelligence")
    print(f"  {datetime.now().strftime('%A, %B %d %Y  •  %I:%M %p')}")

    # --- Auth ---
    YahooFantasyClient.login()
    ctx = YahooFantasyClient.get_context()

    # --- Fetch NBA leagues for the current season ---
    now = datetime.now()
    season_year = now.year if now.month >= 9 else now.year - 1
    leagues: List[League] = ctx.get_leagues("nba", season_year)

    if not leagues:
        print("  ⚠️  No NBA leagues found for this season.")
        sys.exit(0)

    # --- Process leagues ---
    for league in leagues:
        if args.scout:
            _print_header(f"Scouting Report: {league.name}")
            scout = Scout(league)
            report = scout.get_morning_report()
            print(report)
        else:
            _print_header(f"League: {league.name}")
            print(f"  ID: {league.id}  •  Type: {league.league_type}\n")

            for team in league.teams():
                is_mine = "(YOU)" if hasattr(team, "is_owned_by_current_login") and team.is_owned_by_current_login else ""
                print(f"\n  📋 {team.name} — managed by {team.manager.nickname} {is_mine}")
                # For roster display, we don't need to be as robust as for FA fetching,
                # but let's keep it consistent.
                _print_roster(team)

    _print_header("Done ✅")


if __name__ == "__main__":
    main()
