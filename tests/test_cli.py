"""Tests for REPL command parsing."""

from the_front_office.adapters.inbound.cli.repl import parse_command


def test_command_token_is_case_insensitive() -> None:
    assert parse_command("/SCOUT")[0] == "/scout"
    assert parse_command("/Rosters")[0] == "/rosters"


def test_argument_casing_is_preserved() -> None:
    """Player-name lookups depend on casing, so only the command token is
    lowercased."""
    cmd, args, _ = parse_command("/trade Give LeBron James, Get Jayson Tatum")
    assert cmd == "/trade"
    assert args == ["Give", "LeBron", "James,", "Get", "Jayson", "Tatum"]
    assert "LeBron" in args


def test_mock_flag_is_detected_and_stripped_from_args() -> None:
    cmd, args, mock = parse_command("/trade --mock Give LeBron, Get Tatum")
    assert cmd == "/trade"
    assert mock is True
    assert "--mock" not in args
    assert args[0] == "Give"


def test_absent_mock_flag_defaults_false() -> None:
    assert parse_command("/scout")[2] is False


def test_unknown_flags_are_stripped_but_do_not_set_mock() -> None:
    cmd, args, mock = parse_command("/trade --verbose Give LeBron")
    assert mock is False
    assert args == ["Give", "LeBron"]


def test_empty_input_yields_empty_command() -> None:
    assert parse_command("") == ("", [], False)
    assert parse_command("   ") == ("", [], False)


# ── sport-aware dispatch ────────────────────────────────────────────────

from typing import Any  # noqa: E402

import pytest  # noqa: E402

from the_front_office.adapters.inbound.cli import commands as cmd  # noqa: E402
from the_front_office.adapters.inbound.cli import output  # noqa: E402
from the_front_office.adapters.inbound.cli import repl as cli  # noqa: E402
from the_front_office.adapters.inbound.cli.session import Session  # noqa: E402


class FakeProvider:
    sport = "nfl"
    label = "NFL (Sleeper)"

    def list_leagues(self) -> Any:
        from the_front_office.domain.ports import LeagueRef

        return [LeagueRef("L1", "My League", "nfl", "12-team")]

    def roster_rows(self, league_id: str) -> Any:
        return [{"Player": "Star QB", "Pos": "QB"}]


def fake_entry(
    sport: str = "nfl",
    label: str = "NFL (Sleeper)",
    build: Any = None,
    counter: list[int] | None = None,
) -> Any:
    """A real SportEntry with a stubbed build, so the CLI sees what it expects."""
    from the_front_office.bootstrap import SportEntry

    def _build() -> Any:
        if counter is not None:
            counter.append(1)
        return FakeProvider()

    return SportEntry(
        sport=sport,
        label=label,
        build=build or _build,
        is_configured=lambda: True,
        requires="SLEEPER_USERNAME" if sport == "nfl" else "YAHOO_CLIENT_ID",
    )


def test_providers_are_built_once_per_session() -> None:
    """Building the NBA provider opens an OAuth flow; twice would be twice."""
    built: list[int] = []
    entry = fake_entry(counter=built)
    session = Session()
    session.provider(entry)
    session.provider(entry)
    assert built == [1]


def test_no_sport_argument_runs_every_configured_sport() -> None:
    entries = [fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")]
    assert cmd._resolve_sports([], entries) == entries


def test_a_named_sport_runs_only_that_one() -> None:
    nfl, nba = fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")
    resolved = cmd._resolve_sports(["nfl"], [nfl, nba])
    assert [e.sport for e in resolved] == ["nfl"]


def test_an_unknown_sport_resolves_to_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd._resolve_sports(["cricket"], [fake_entry()]) == []
    assert "Unknown sport" in capsys.readouterr().out


def test_an_unconfigured_sport_names_what_to_set(capsys: pytest.CaptureFixture[str]) -> None:
    """Asking for a sport you have no credentials for must explain, not crash."""
    assert cmd._resolve_sports(["nba"], [fake_entry("nfl")]) == []
    out = capsys.readouterr().out
    assert "not configured" in out
    assert "YAHOO_CLIENT_ID" in out


def test_roster_renders_rows_for_the_selected_sport(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._cmd_roster(Session(), [fake_entry()], [])
    out = capsys.readouterr().out
    assert "My League" in out
    assert "Star QB" in out


def test_leagues_lists_every_configured_sport(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._cmd_leagues(Session(), [fake_entry()])
    out = capsys.readouterr().out
    assert "My League" in out
    assert "12-team" in out


def test_a_platform_failure_is_reported_not_raised(capsys: pytest.CaptureFixture[str]) -> None:
    from the_front_office.domain.errors import LeagueNotFoundError

    def _boom() -> Any:
        raise LeagueNotFoundError("SLEEPER_USERNAME is not set in .env")

    cmd._cmd_roster(Session(), [fake_entry(build=_boom)], [])
    assert "SLEEPER_USERNAME" in capsys.readouterr().out


def test_quit_raises_the_sentinel() -> None:
    with pytest.raises(cli.QuitRequested):
        cli._dispatch(Session(), [], "/quit", [], False)


def test_unknown_command_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    cli._dispatch(Session(), [], "/nonsense", [], False)
    assert "Unknown command" in capsys.readouterr().out


def test_help_names_the_configured_sports(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._print_help([fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")])
    assert "nfl | nba" in capsys.readouterr().out


def test_rows_are_printed_with_aligned_columns(capsys: pytest.CaptureFixture[str]) -> None:
    output._print_rows([{"Player": "A", "Pos": "QB"}, {"Player": "Longer Name", "Pos": "RB"}])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len({len(ln.rstrip()) for ln in lines}) <= 2  # header, rule and rows align


def test_an_empty_roster_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    output._print_rows([])
    assert "no players found" in capsys.readouterr().out


def test_trade_reports_when_no_sport_supports_it(capsys: pytest.CaptureFixture[str]) -> None:
    """Football is configured but has no trade path yet."""
    cmd._cmd_trade(Session(), [fake_entry("nfl")], ["Give A, Get B"], False)
    assert "supports trade evaluation" in capsys.readouterr().out


def test_trade_usage_is_shown_without_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._cmd_trade(Session(), [fake_entry("nfl")], [], False)
    assert "Usage: /trade" in capsys.readouterr().out


def test_help_names_which_sports_can_trade(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._print_help([fake_entry("nfl")])
    out = capsys.readouterr().out
    assert "Evaluate a trade (none)" in out


# ── command bodies ──────────────────────────────────────────────────────


class RecordingProvider(FakeProvider):
    """A provider whose context and engine calls can be observed."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def build_context(self, league_id: str) -> Any:
        from the_front_office.domain.models import SportContext

        if self.error:
            raise self.error
        return SportContext(prompt="PROMPT")

    def build_trade_context(self, league_id: str, proposal: Any) -> Any:
        from the_front_office.domain.models import SportContext

        if self.error:
            raise self.error
        return SportContext(prompt="TRADE PROMPT")


def _entry_with(provider: Any, sport: str = "nfl", trades: bool = False) -> Any:
    from the_front_office.bootstrap import SportEntry

    return SportEntry(
        sport=sport,
        label="NFL (Sleeper)",
        build=lambda: provider,
        is_configured=lambda: True,
        requires="SLEEPER_USERNAME",
        supports_trades=trades,
    )


def test_scout_renders_a_report(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from conftest import FakeAI

    monkeypatch.setattr(cmd, "scout_engine", lambda provider, mock: _scout_with(provider, FakeAI()))
    cmd._cmd_scout(Session(), [_entry_with(RecordingProvider())], [], True)
    out = capsys.readouterr().out
    assert "My League" in out
    assert "SITUATION" in out  # the rendered report


def _scout_with(provider: Any, ai: Any) -> Any:
    from the_front_office.application.scouting import ScoutEngine

    return ScoutEngine(provider, ai=ai)


def test_scout_reports_a_platform_failure(capsys: pytest.CaptureFixture[str]) -> None:
    from the_front_office.domain.errors import TeamNotFoundError

    entry = _entry_with(RecordingProvider(error=TeamNotFoundError("Some League")))
    cmd._cmd_scout(Session(), [entry], [], True)
    assert "Some League" in capsys.readouterr().out


def test_scout_warns_when_a_sport_has_no_leagues(capsys: pytest.CaptureFixture[str]) -> None:
    class NoLeagues(RecordingProvider):
        def list_leagues(self) -> Any:
            return []

    cmd._cmd_scout(Session(), [_entry_with(NoLeagues())], [], True)
    assert "No NFL (Sleeper) leagues" in capsys.readouterr().out


def test_trade_renders_a_verdict(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from conftest import FakeAI

    from the_front_office.application.trading import TradeEngine

    provider = RecordingProvider()
    monkeypatch.setattr(cmd, "trade_engine", lambda p, mock: TradeEngine(p, ai=FakeAI()))
    cmd._cmd_trade(Session(), [_entry_with(provider, trades=True)], ["Give", "A,", "Get", "B"], True)
    out = capsys.readouterr().out
    assert "VERDICT" in out


def test_trade_reports_a_domain_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from conftest import FakeAI

    from the_front_office.application.trading import TradeEngine
    from the_front_office.domain.errors import PlayerNotFoundError

    provider = RecordingProvider(error=PlayerNotFoundError(["Ghost"]))
    monkeypatch.setattr(cmd, "trade_engine", lambda p, mock: TradeEngine(p, ai=FakeAI()))
    cmd._cmd_trade(Session(), [_entry_with(provider, trades=True)], ["x"], True)
    assert "Ghost" in capsys.readouterr().out
