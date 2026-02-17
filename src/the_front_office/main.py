"""
main.py — Interactive entry point for The Front Office.

Authenticates once with Yahoo Fantasy, then waits for slash commands
to run scouting reports, view rosters, etc.
"""

import sys
from datetime import datetime
from typing import List
from the_front_office.config.logging import setup_logging
from the_front_office.clients.yahoo.client import YahooFantasyClient
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


def _print_help() -> None:
    """Print available commands."""
    print()
    print("  Available commands:")
    print("  ─────────────────────────────────────")
    print("  /scout          Run the Morning Scout Report (AI waiver analysis)")
    print("  /scout --mock   Use mock AI responses (for testing)")
    print("  /rosters        Show all team rosters in the league")
    print("  /my-roster      Show only your roster")
    print("  /matchup        Show current matchup scores")
    print("  /help           Show this help message")
    print("  /quit           Exit the program")
    print()


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

def _cmd_scout(leagues: List[League], mock: bool = False) -> None:
    """Run the scout report for all leagues."""
    for league in leagues:
        _print_header(f"Scouting Report: {league.name}")
        scout = Scout(league, mock_ai=mock)
        report = scout.get_report()
        print(report)


def _cmd_rosters(leagues: List[League]) -> None:
    """Show all team rosters."""
    for league in leagues:
        _print_header(f"League: {league.name}")
        print(f"  ID: {league.id}  •  Type: {league.league_type}\n")

        for team in league.teams():
            is_mine = "(YOU)" if hasattr(team, "is_owned_by_current_login") and team.is_owned_by_current_login else ""
            print(f"\n  📋 {team.name} — managed by {team.manager.nickname} {is_mine}")
            _print_roster(team)


def _cmd_my_roster(leagues: List[League]) -> None:
    """Show only the user's roster."""
    for league in leagues:
        yahoo = YahooFantasyClient(league)
        my_team = yahoo.get_user_team()
        if my_team:
            _print_header(f"Your Roster: {my_team.name} ({league.name})")
            _print_roster(my_team)
        else:
            print(f"  ⚠️  Could not identify your team in {league.name}")


def _cmd_matchup(leagues: List[League]) -> None:
    """Show current matchup context."""
    for league in leagues:
        yahoo = YahooFantasyClient(league)
        my_team = yahoo.get_user_team()
        if my_team:
            _print_header(f"Matchup: {league.name}")
            context = yahoo.get_matchup_context(my_team)
            print(f"  {context}")
        else:
            print(f"  ⚠️  Could not identify your team in {league.name}")


# ---------------------------------------------------------------------------
# Interactive Loop
# ---------------------------------------------------------------------------

def main() -> None:
    """Authenticate once, then run an interactive command loop."""
    setup_logging()

    _print_header("🏀 The Front Office — NBA Fantasy Intelligence")
    print(f"  {datetime.now().strftime('%A, %B %d %Y  •  %I:%M %p')}")

    # --- Auth (once) ---
    print("\n  🔐 Authenticating with Yahoo Fantasy...")
    YahooFantasyClient.login()
    ctx = YahooFantasyClient.get_context()

    # --- Fetch leagues (once) ---
    now = datetime.now()
    season_year = now.year if now.month >= 9 else now.year - 1
    leagues: List[League] = ctx.get_leagues("nba", season_year)

    if not leagues:
        print("  ⚠️  No NBA leagues found for this season.")
        sys.exit(0)

    print(f"  ✅ Found {len(leagues)} league(s): {', '.join(l.name for l in leagues)}")
    _print_help()

    # --- REPL ---
    while True:
        try:
            raw = input("  ⚡ ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            _print_header("Goodbye 👋")
            break

        if not raw:
            continue

        parts = raw.split()
        cmd = parts[0]
        flags = parts[1:]

        if cmd == "/scout":
            mock = "--mock" in flags
            _cmd_scout(leagues, mock=mock)
        elif cmd == "/rosters":
            _cmd_rosters(leagues)
        elif cmd in ("/my-roster", "/roster"):
            _cmd_my_roster(leagues)
        elif cmd == "/matchup":
            _cmd_matchup(leagues)
        elif cmd == "/help":
            _print_help()
        elif cmd in ("/quit", "/exit", "/q"):
            _print_header("Goodbye 👋")
            break
        else:
            print(f"  ❓ Unknown command: {cmd}. Type /help for available commands.")

    _print_header("Done ✅")


if __name__ == "__main__":
    main()
