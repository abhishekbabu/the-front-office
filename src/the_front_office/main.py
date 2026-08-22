"""Interactive entry point.

Sport-neutral: the registry decides which sports are available, and a platform
is only contacted when a command actually needs it. Nothing here knows about
Yahoo or Sleeper.
"""

import contextlib
import sys
import textwrap
from datetime import datetime
from typing import TYPE_CHECKING, Union

from the_front_office.config.logging import setup_logging
from the_front_office.exceptions import FrontOfficeError
from the_front_office.render import render_scout_report, render_trade_verdict
from the_front_office.report.engine import ScoutEngine
from the_front_office.sports.base import SportProvider
from the_front_office.sports.registry import SportEntry, configured_sports, find

if TYPE_CHECKING:
    from google.genai.chats import Chat

    from the_front_office.clients.gemini.types import MockChatSession

# Graceful fallback on systems without readline
with contextlib.suppress(ImportError):
    import readline  # noqa: F401 — enables up/down arrow history in input()


# ---------------------------------------------------------------------------
# Providers, built once and only when needed
# ---------------------------------------------------------------------------


class Session:
    """Holds providers, building each on first use.

    Deferring construction is what lets a football-only user reach `/football`:
    building the NBA provider opens a Yahoo OAuth flow, and doing that at
    startup made the CLI exit before the prompt for anyone without Yahoo
    credentials.
    """

    def __init__(self) -> None:
        self._providers: dict[str, SportProvider] = {}

    def provider(self, entry: SportEntry) -> SportProvider:
        if entry.sport not in self._providers:
            self._providers[entry.sport] = entry.build()
        return self._providers[entry.sport]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_header(text: str) -> None:
    """Print a styled section header."""
    width = 60
    print("\n" + "═" * width)
    print(f"  {text}")
    print("═" * width)


def _print_rows(rows: list[dict[str, str]]) -> None:
    """Print table rows with columns sized to their content."""
    if not rows:
        print("  (no players found)")
        return
    columns = list(rows[0])
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    print("  " + "  ".join(c.ljust(widths[c]) for c in columns))
    print("  " + "  ".join("─" * widths[c] for c in columns))
    for row in rows:
        print("  " + "  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def _interactive_followup(
    chat: Union["Chat", "MockChatSession", None],
    noun: str,
) -> None:
    """Run a follow-up Q&A loop against an open AI chat session."""
    if not chat:
        return

    print("\n  " + "─" * 60)
    print(f"  💬 Interactive Mode: Ask follow-up questions about this {noun}.")
    print("     Type your question or press Enter to continue.")
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
    since player-name lookups against the platform depend on it.
    """
    parts = raw.split()
    if not parts:
        return ("", [], False)

    cmd = parts[0].lower()
    rest = parts[1:]
    mock = "--mock" in rest
    args = [a for a in rest if not a.startswith("--")]
    return (cmd, args, mock)


def _print_help(entries: list[SportEntry]) -> None:
    """Print available commands, naming the sports that are configured."""
    keys = " | ".join(e.sport for e in entries) or "none configured"
    tradeable = ", ".join(e.sport for e in entries if e.supports_trades) or "none"
    print()
    print("  Available commands:")
    print("  ─────────────────────────────────────")
    rows = [
        (f"/scout [{keys}]", "Scouting report. No sport runs every configured one."),
        ("/roster [sport]", "Your roster"),
        ("/leagues", "Every league, per sport"),
        ("/trade <txt>", f"Evaluate a trade ({tradeable})"),
        ("/help", "Show this help message"),
        ("/quit", "Exit the program"),
    ]
    width = max(len(c) for c, _ in rows)
    for command, description in rows:
        print(f"  {command.ljust(width)}   {description}")
    print()
    print("  Add --mock to /scout or /trade to skip the AI call.")
    print()


def _resolve_sports(args: list[str], entries: list[SportEntry]) -> list[SportEntry]:
    """Which sports a command should run for.

    No argument means every configured sport; a named one means just that,
    provided it is configured.
    """
    if not args:
        return entries

    key = args[0].lower().lstrip("/")
    # Match within the configured set first. Consulting the global registry
    # first and then testing membership lets the two disagree — which is how a
    # caller passing its own entries gets told a sport it just supplied is
    # unconfigured.
    for entry in entries:
        if entry.sport == key:
            return [entry]

    known = find(key)
    if known is None:
        print(f"  ❓ Unknown sport: {args[0]}")
    else:
        print(f"  ⚠️  {known.label} is not configured. Set {known.requires} in .env.")
    return []


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------


def _cmd_scout(session: Session, entries: list[SportEntry], args: list[str], mock: bool) -> None:
    """Run a scouting report for each requested sport and league."""
    for entry in _resolve_sports(args, entries):
        try:
            provider = session.provider(entry)
            refs = provider.list_leagues()
        except FrontOfficeError as e:
            print(f"  ❌ {entry.label}: {e}")
            continue

        if not refs:
            print(f"  ⚠️  No {entry.label} leagues found for this season.")
            continue

        engine = ScoutEngine(provider, mock_ai=mock)
        for ref in refs:
            _print_header(f"{entry.label} — {ref.name}")
            if ref.detail:
                print(f"  {ref.detail}")
            print("  ⏳ Gathering league state and building the report...")
            try:
                report, chat = engine.start_analysis(ref.league_id)
            except FrontOfficeError as e:
                print(f"  ❌ {e}")
                continue
            print("\n" + render_scout_report(report))
            _interactive_followup(chat, "report")


def _cmd_roster(session: Session, entries: list[SportEntry], args: list[str]) -> None:
    """Show the user's roster for each requested sport."""
    for entry in _resolve_sports(args, entries):
        try:
            provider = session.provider(entry)
            for ref in provider.list_leagues():
                _print_header(f"{entry.label} — {ref.name}")
                _print_rows(provider.squad_rows(ref.league_id))
        except FrontOfficeError as e:
            print(f"  ❌ {entry.label}: {e}")


def _cmd_leagues(session: Session, entries: list[SportEntry]) -> None:
    """List every league across configured sports."""
    for entry in entries:
        _print_header(entry.label)
        try:
            refs = session.provider(entry).list_leagues()
        except FrontOfficeError as e:
            print(f"  ❌ {e}")
            continue
        if not refs:
            print("  (none this season)")
        for ref in refs:
            print(f"  • {ref.name}" + (f"  —  {ref.detail}" if ref.detail else ""))


def _cmd_trade(session: Session, entries: list[SportEntry], args: list[str], mock: bool) -> None:
    """Evaluate a trade. NBA only for now."""
    from the_front_office.trade.engine import TradeEvaluator

    if not args:
        print("  ⚠️  Usage: /trade <trade description>")
        print("  Example: /trade Give LeBron James, Get Jayson Tatum")
        return

    tradeable = [e for e in entries if e.supports_trades]
    if not tradeable:
        print("  ⚠️  No configured sport supports trade evaluation yet.")
        return
    entry = tradeable[0]

    trade_text = " ".join(args)
    provider = session.provider(entry)
    for ref in provider.list_leagues():
        _print_header(f"Trade Evaluation — {ref.name}")
        print("  ⏳ Parsing, enriching and evaluating...")
        try:
            league = getattr(provider, "_select")(ref.league_id)  # noqa: B009
            verdict, chat = TradeEvaluator(league, mock_ai=mock).evaluate(trade_text)
        except FrontOfficeError as e:
            print(f"  ❌ {e}")
            continue
        print("\n" + render_trade_verdict(verdict))
        _interactive_followup(chat, "trade")


# ---------------------------------------------------------------------------
# Interactive Loop
# ---------------------------------------------------------------------------


def _configure_console() -> None:
    """Make stdout/stderr able to carry the UI's emoji and box-drawing glyphs.

    Python writes to a Windows *console* as UTF-16 and handles them fine, but as
    soon as output is redirected to a file or pipe it falls back to the locale
    encoding — cp1252 on most Windows installs — where every one of those
    characters raises UnicodeEncodeError and takes the process down.

    Reconfiguring to UTF-8 fixes redirection; errors="replace" means a terminal
    that genuinely cannot represent a glyph degrades to a placeholder instead of
    crashing. No-op where the streams are already UTF-8, or replaced entirely
    (pytest's capture, for instance, offers no reconfigure()).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # Already detached, or not reconfigurable — the UI is still usable.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


class QuitRequested(Exception):
    """Raised by _dispatch when the user asks to exit."""


def _dispatch(session: Session, entries: list[SportEntry], cmd: str, args: list[str], mock: bool) -> None:
    """Route one parsed command to its handler.

    Raises:
        QuitRequested: the user asked to exit.
    """
    if cmd == "/scout":
        _cmd_scout(session, entries, args, mock)
    elif cmd in ("/roster", "/rosters", "/my-roster"):
        _cmd_roster(session, entries, args)
    elif cmd == "/leagues":
        _cmd_leagues(session, entries)
    elif cmd == "/trade":
        _cmd_trade(session, entries, args, mock)
    elif cmd == "/help":
        _print_help(entries)
    elif cmd in ("/quit", "/exit", "/q"):
        raise QuitRequested
    else:
        print(f"  ❓ Unknown command: {cmd}. Type /help for available commands.")


def main() -> None:
    """Start a REPL over whichever sports are configured."""
    _configure_console()
    setup_logging()

    _print_header("🏆 The Front Office — Fantasy Intelligence")
    print(f"  {datetime.now().strftime('%A, %B %d %Y  •  %I:%M %p')}")

    entries = configured_sports()
    if not entries:
        print("\n  ⚠️  No sports configured. Set one of these in .env:")
        from the_front_office.sports.registry import all_sports

        for entry in all_sports():
            print(f"       {entry.label}: {entry.requires}")
        sys.exit(1)

    print(f"\n  ✅ Configured: {', '.join(e.label for e in entries)}")
    unconfigured = _unconfigured()
    if unconfigured:
        print(
            textwrap.fill(
                "  Also available: " + "; ".join(f"{e.label} (set {e.requires})" for e in unconfigured),
                width=78,
                subsequent_indent="    ",
            )
        )
    _print_help(entries)

    session = Session()

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
            _dispatch(session, entries, cmd, args, mock)
        except FrontOfficeError as e:
            # Safety net — handlers render their own errors, but a session must
            # never die because one command raised.
            print(f"  ❌ {e}")
        except QuitRequested:
            _print_header("Goodbye 👋")
            break

    _print_header("Done ✅")


def _unconfigured() -> list[SportEntry]:
    from the_front_office.sports.registry import all_sports

    configured = {e.sport for e in configured_sports()}
    return [e for e in all_sports() if e.sport not in configured]


if __name__ == "__main__":
    main()
