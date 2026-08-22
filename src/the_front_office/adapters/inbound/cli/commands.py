"""One function per slash command."""

from the_front_office.adapters.inbound.cli.output import _interactive_followup, _print_header, _print_rows
from the_front_office.adapters.inbound.cli.render import render_scout_report, render_trade_verdict
from the_front_office.adapters.inbound.cli.session import Session
from the_front_office.bootstrap import SportEntry, find, scout_engine, trade_engine
from the_front_office.domain.errors import FrontOfficeError


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
    # Match within the configured set first; the registry is only consulted to
    # tell an unknown sport apart from an unconfigured one.
    for entry in entries:
        if entry.sport == key:
            return [entry]

    known = find(key)
    if known is None:
        print(f"  ❓ Unknown sport: {args[0]}")
    else:
        print(f"  ⚠️  {known.label} is not configured. Set {known.requires} in .env.")
    return []


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

        engine = scout_engine(provider, mock)
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
                _print_rows(provider.roster_rows(ref.league_id))
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
    """Evaluate a trade for the first sport that supports it."""
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
    engine = trade_engine(provider, mock)  # type: ignore[arg-type]
    for ref in provider.list_leagues():
        _print_header(f"{entry.label} — Trade Evaluation — {ref.name}")
        print("  ⏳ Parsing, enriching and evaluating...")
        try:
            verdict, chat = engine.evaluate(ref.league_id, trade_text)
        except FrontOfficeError as e:
            print(f"  ❌ {e}")
            continue
        print("\n" + render_trade_verdict(verdict))
        _interactive_followup(chat, "trade")
