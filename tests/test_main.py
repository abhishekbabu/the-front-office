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
