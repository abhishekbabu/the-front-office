"""The interactive loop.

Sport-neutral: the registry decides which sports are available, and a platform
is only contacted when a command actually needs it.
"""

import contextlib
import sys
import textwrap
from datetime import datetime

from the_front_office.adapters.inbound.cli.commands import (
    _cmd_leagues,
    _cmd_roster,
    _cmd_scout,
    _cmd_trade,
    _print_help,
)
from the_front_office.adapters.inbound.cli.output import _print_header, print_error
from the_front_office.adapters.inbound.cli.session import Session
from the_front_office.bootstrap import SportEntry, all_sports, configured_sports
from the_front_office.config.logging import setup_logging
from the_front_office.config.telemetry import setup_telemetry
from the_front_office.domain.errors import FrontOfficeError

# Graceful fallback on systems without readline
with contextlib.suppress(ImportError):
    import readline  # noqa: F401 — enables up/down arrow history in input()


def parse_command(raw: str) -> tuple[str, list[str]]:
    """Split a REPL line into a command and its positional arguments.

    The command token is case-insensitive, but positional arguments are not:
    `/trade Give LeBron, Get Tatum` must reach the AI with its casing intact,
    since player-name lookups against the platform depend on it.
    """
    parts = raw.split()
    if not parts:
        return ("", [])

    cmd = parts[0].lower()
    args = [a for a in parts[1:] if not a.startswith("--")]
    return (cmd, args)


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


def _dispatch(session: Session, entries: list[SportEntry], cmd: str, args: list[str]) -> None:
    """Route one parsed command to its handler.

    Raises:
        QuitRequested: the user asked to exit.
    """
    if cmd == "/scout":
        _cmd_scout(session, entries, args)
    elif cmd in ("/roster", "/rosters", "/my-roster"):
        _cmd_roster(session, entries, args)
    elif cmd == "/leagues":
        _cmd_leagues(session, entries)
    elif cmd == "/trade":
        _cmd_trade(session, entries, args)
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
    # After setup_logging, so the bridge attaches to a root logger that already
    # has its level and its console handler.
    setup_telemetry("front-office-cli")

    _print_header("🏆 The Front Office — Fantasy Intelligence")
    print(f"  {datetime.now().strftime('%A, %B %d %Y  •  %I:%M %p')}")

    entries = configured_sports()
    if not entries:
        print("\n  ⚠️  No sports configured. Set one of these in .env:")
        from the_front_office.bootstrap import all_sports

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

    while True:
        try:
            raw = input("  ⚡ ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            _print_header("Goodbye 👋")
            break

        if not raw:
            continue

        cmd, args = parse_command(raw)

        try:
            _dispatch(session, entries, cmd, args)
        except FrontOfficeError as e:
            # Safety net — handlers render their own errors, but a session must
            # never die because one command raised.
            print_error(e)
        except QuitRequested:
            _print_header("Goodbye 👋")
            break

    _print_header("Done ✅")


def _unconfigured() -> list[SportEntry]:

    configured = {e.sport for e in configured_sports()}
    return [e for e in all_sports() if e.sport not in configured]


if __name__ == "__main__":
    main()
