"""Tests for REPL command parsing."""

from the_front_office.main import parse_command


def test_command_token_is_case_insensitive() -> None:
    assert parse_command("/SCOUT")[0] == "/scout"
    assert parse_command("/Rosters")[0] == "/rosters"


def test_argument_casing_is_preserved() -> None:
    """Regression: the REPL used to lowercase the whole line, so player names
    reached Gemini and Yahoo's search as 'lebron james'."""
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

from the_front_office import main as cli  # noqa: E402


class FakeProvider:
    sport = "nfl"
    label = "NFL (Sleeper)"

    def list_leagues(self) -> Any:
        from the_front_office.sports.base import LeagueRef

        return [LeagueRef("L1", "My League", "nfl", "12-team")]

    def squad_rows(self, league_id: str) -> Any:
        return [{"Player": "Star QB", "Pos": "QB"}]


def fake_entry(
    sport: str = "nfl",
    label: str = "NFL (Sleeper)",
    build: Any = None,
    counter: list[int] | None = None,
) -> Any:
    """A real SportEntry with a stubbed build, so the CLI sees what it expects."""
    from the_front_office.sports.registry import SportEntry

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
    session = cli.Session()
    session.provider(entry)
    session.provider(entry)
    assert built == [1]


def test_no_sport_argument_runs_every_configured_sport() -> None:
    entries = [fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")]
    assert cli._resolve_sports([], entries) == entries


def test_a_named_sport_runs_only_that_one() -> None:
    nfl, nba = fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")
    resolved = cli._resolve_sports(["nfl"], [nfl, nba])
    assert [e.sport for e in resolved] == ["nfl"]


def test_an_unknown_sport_resolves_to_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli._resolve_sports(["cricket"], [fake_entry()]) == []
    assert "Unknown sport" in capsys.readouterr().out


def test_an_unconfigured_sport_names_what_to_set(capsys: pytest.CaptureFixture[str]) -> None:
    """Asking for a sport you have no credentials for must explain, not crash."""
    assert cli._resolve_sports(["nba"], [fake_entry("nfl")]) == []
    out = capsys.readouterr().out
    assert "not configured" in out
    assert "YAHOO_CLIENT_ID" in out


def test_roster_renders_rows_for_the_selected_sport(capsys: pytest.CaptureFixture[str]) -> None:
    cli._cmd_roster(cli.Session(), [fake_entry()], [])
    out = capsys.readouterr().out
    assert "My League" in out
    assert "Star QB" in out


def test_leagues_lists_every_configured_sport(capsys: pytest.CaptureFixture[str]) -> None:
    cli._cmd_leagues(cli.Session(), [fake_entry()])
    out = capsys.readouterr().out
    assert "My League" in out
    assert "12-team" in out


def test_a_platform_failure_is_reported_not_raised(capsys: pytest.CaptureFixture[str]) -> None:
    from the_front_office.exceptions import LeagueNotFoundError

    def _boom() -> Any:
        raise LeagueNotFoundError("SLEEPER_USERNAME is not set in .env")

    cli._cmd_roster(cli.Session(), [fake_entry(build=_boom)], [])
    assert "SLEEPER_USERNAME" in capsys.readouterr().out


def test_quit_raises_the_sentinel() -> None:
    with pytest.raises(cli.QuitRequested):
        cli._dispatch(cli.Session(), [], "/quit", [], False)


def test_unknown_command_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    cli._dispatch(cli.Session(), [], "/nonsense", [], False)
    assert "Unknown command" in capsys.readouterr().out


def test_help_names_the_configured_sports(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_help([fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")])
    assert "nfl | nba" in capsys.readouterr().out


def test_rows_are_printed_with_aligned_columns(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_rows([{"Player": "A", "Pos": "QB"}, {"Player": "Longer Name", "Pos": "RB"}])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len({len(ln.rstrip()) for ln in lines}) <= 2  # header, rule and rows align


def test_an_empty_roster_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_rows([])
    assert "no players found" in capsys.readouterr().out


def test_trade_reports_when_no_sport_supports_it(capsys: pytest.CaptureFixture[str]) -> None:
    """Football is configured but has no trade path yet."""
    cli._cmd_trade(cli.Session(), [fake_entry("nfl")], ["Give A, Get B"], False)
    assert "supports trade evaluation" in capsys.readouterr().out


def test_trade_usage_is_shown_without_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    cli._cmd_trade(cli.Session(), [fake_entry("nfl")], [], False)
    assert "Usage: /trade" in capsys.readouterr().out


def test_help_names_which_sports_can_trade(capsys: pytest.CaptureFixture[str]) -> None:
    cli._print_help([fake_entry("nfl")])
    out = capsys.readouterr().out
    assert "Evaluate a trade (none)" in out
