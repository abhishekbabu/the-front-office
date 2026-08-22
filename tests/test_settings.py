"""Tests for env-var validation in AppSettings."""

import pytest
from pydantic import ValidationError

from the_front_office.config.settings import AppSettings


def _settings(**overrides: object) -> AppSettings:
    """Build settings from explicit values, ignoring any real .env on disk."""
    return AppSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_match_the_documented_values() -> None:
    s = _settings()
    assert s.yahoo_max_weekly_adds == 3
    assert s.log_level == "INFO"
    assert s.nba_api_delay == 4.0
    assert s.yahoo_redirect_uri == "https://localhost:8080"


def test_non_numeric_add_limit_fails_loudly() -> None:
    """Previously `int(os.getenv(...))` raised a bare ValueError at import time."""
    with pytest.raises(ValidationError, match="yahoo_max_weekly_adds"):
        _settings(yahoo_max_weekly_adds="three")


def test_negative_add_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(yahoo_max_weekly_adds=-1)


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError, match="log_level"):
        _settings(log_level="CHATTY")


def test_log_level_is_case_insensitive() -> None:
    assert _settings(log_level="debug").log_level == "DEBUG"


def test_missing_credentials_are_none_not_crashes() -> None:
    """--mock must work with no credentials at all."""
    s = _settings()
    assert s.gemini_api_key is None
    assert s.yahoo_client_id is None


def test_zero_api_delay_is_allowed_but_negative_is_not() -> None:
    assert _settings(nba_api_delay=0.0).nba_api_delay == 0.0
    with pytest.raises(ValidationError):
        _settings(nba_api_delay=-1.0)
