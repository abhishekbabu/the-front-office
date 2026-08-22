"""
main.py — Interactive entry point for The Front Office.

Authenticates once with Yahoo Fantasy, then waits for slash commands
to run scouting reports, view rosters, etc.
"""

import contextlib
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Union

from yahoofantasy import League, Team  # type: ignore[import-untyped]

from the_front_office.clients.yahoo.client import YahooFantasyClient
from the_front_office.config.logging import setup_logging
from the_front_office.exceptions import FrontOfficeError
from the_front_office.scout import Scout
from the_front_office.trade.engine import TradeEvaluator

if TYPE_CHECKING:
    from google.genai.chats import Chat

    from the_front_office.clients.gemini.types import MockChatSession

# Graceful fallback on systems without readline
with contextlib.suppress(ImportError):
    import readline  # noqa: F401 — enables up/down arrow history in input()


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


def _interactive_followup(
    chat: Union["Chat", "MockChatSession"] | None,
    noun: str,
) -> None:
    """Run a follow-up Q&A loop against an open AI chat session."""
    if not chat:
        return

    print("\n  " + "─" * 60)
    print(f"  💬 Interactive Mode: Ask follow-up questions about this {noun}.")
    print("     Type your question or press Enter to continue to next league.")
    print("  " + "─" * 60)

    while True:
        try:
            user_input = input("\n  Query > ").strip()
            if not user_input or user_input.lower() in ("/quit", "/exit", "q"):
                break

            print("  ⏳ Thinking...")
            response = chat.send_message(user_input)
            print(f"\n  🤖 {response.text}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"  ❌ Error: {e}")
            break


def parse_command(raw: str) -> tuple[str, list[str], bool]:
    """Split a REPL line into (command, positional args, mock flag).

    The command token is case-insensitive, but positional arguments are not:
    `/trade Give LeBron, Get Tatum` must reach the AI with its casing intact,
    since player-name lookups against Yahoo depend on it.
    """
    parts = raw.split()
    if not parts:
        return ("", [], False)

    cmd = parts[0].lower()
    rest = parts[1:]
    mock = "--mock" in rest
    args = [a for a in rest if not a.startswith("--")]
    return (cmd, args, mock)


def _print_help() -> None:
    """Print available commands."""
    print()
    print("  Available commands:")
    print("  ─────────────────────────────────────")
    print("  /scout               Run the Morning Scout Report (AI waiver analysis)")
    print("  /scout --mock        Use mock AI responses (for testing)")
    print("  /trade <txt>         Evaluate a trade (e.g. '/trade Give LeBron, Get Tatum')")
    print("  /trade --mock <txt>  Evaluate a trade with mock AI responses")
    print("  /rosters             Show all team rosters in the league")
    print("  /my-roster           Show only your roster")
    print("  /matchup             Show current matchup scores")
    print("  /help                Show this help message")
    print("  /quit                Exit the program")
    print()


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------


def _cmd_scout(leagues: list[League], mock: bool = False) -> None:
    """Run the scout report for all leagues."""
    for league in leagues:
        _print_header(f"Scouting Report: {league.name}")
        scout = Scout(league, mock_ai=mock)

        print("  ⏳ Analyzing roster, free agents, and schedule... (this may take a moment)")
        try:
            report, chat = scout.start_analysis()
        except FrontOfficeError as e:
            print(f"  ❌ {e}")
            continue
        print("\n" + report)

        _interactive_followup(chat, "report")


def _cmd_trade(leagues: list[League], args: list[str], mock: bool = False) -> None:
    """Run the trade evaluator."""
    if not args:
        print("  ⚠️  Usage: /trade <trade description>")
        print("  Example: /trade Give LeBron James, Get Jayson Tatum")
        print("  Mock Example: /trade --mock Give LeBron James, Get Jayson Tatum")
        return

    trade_text = " ".join(args)

    for league in leagues:
        _print_header(f"Trade Evaluation: {league.name}")
        evaluator = TradeEvaluator(league, mock_ai=mock)

        print("  ⏳ Analyzing trade... (parsing & enriching data)")
        try:
            report, chat = evaluator.evaluate(trade_text)
        except FrontOfficeError as e:
            print(f"  ❌ {e}")
            continue
        print("\n" + report)

        _interactive_followup(chat, "trade")


def _cmd_rosters(leagues: list[League]) -> None:
    """Show all team rosters."""
    for league in leagues:
        _print_header(f"League: {league.name}")
        print(f"  ID: {league.id}  •  Type: {league.league_type}\n")

        for team in league.teams():
            is_mine = "(YOU)" if hasattr(team, "is_owned_by_current_login") and team.is_owned_by_current_login else ""
            print(f"\n  📋 {team.name} — managed by {team.manager.nickname} {is_mine}")
            _print_roster(team)


def _cmd_my_roster(leagues: list[League]) -> None:
    """Show only the user's roster."""
    for league in leagues:
        try:
            my_team = YahooFantasyClient(league).get_user_team()
        except FrontOfficeError as e:
            print(f"  ⚠️  {e}")
            continue
        _print_header(f"Your Roster: {my_team.name} ({league.name})")
        _print_roster(my_team)


def _cmd_matchup(leagues: list[League]) -> None:
    """Show current matchup context."""
    for league in leagues:
        yahoo = YahooFantasyClient(league)
        try:
            my_team = yahoo.get_user_team()
        except FrontOfficeError as e:
            print(f"  ⚠️  {e}")
            continue
        _print_header(f"Matchup: {league.name}")
        print(f"  {yahoo.get_matchup_context(my_team)}")


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
    leagues: list[League] = ctx.get_leagues("nba", season_year)

    if not leagues:
        print("  ⚠️  No NBA leagues found for this season.")
        sys.exit(0)

    print(f"  ✅ Found {len(leagues)} league(s): {', '.join(lg.name for lg in leagues)}")
    _print_help()

    # --- REPL ---
    while True:
        try:
            raw = input("  ⚡ ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            _print_header("Goodbye 👋")
            break

        if not raw:
            continue

        cmd, args, mock = parse_command(raw)

        try:
            _dispatch(leagues, cmd, args, mock)
        except FrontOfficeError as e:
            # Safety net — handlers render their own errors, but a session must
            # never die because one command raised.
            print(f"  ❌ {e}")
        except QuitRequested:
            _print_header("Goodbye 👋")
            break

    _print_header("Done ✅")


class QuitRequested(Exception):
    """Raised by _dispatch when the user asks to exit."""


def _dispatch(leagues: list[League], cmd: str, args: list[str], mock: bool) -> None:
    """Route one parsed command to its handler.

    Raises:
        QuitRequested: the user asked to exit.
    """
    if cmd == "/scout":
        _cmd_scout(leagues, mock=mock)
    elif cmd == "/trade":
        _cmd_trade(leagues, args, mock=mock)
    elif cmd == "/rosters":
        _cmd_rosters(leagues)
    elif cmd in ("/my-roster", "/roster"):
        _cmd_my_roster(leagues)
    elif cmd == "/matchup":
        _cmd_matchup(leagues)
    elif cmd == "/help":
        _print_help()
    elif cmd in ("/quit", "/exit", "/q"):
        raise QuitRequested
    else:
        print(f"  ❓ Unknown command: {cmd}. Type /help for available commands.")


if __name__ == "__main__":
    main()
