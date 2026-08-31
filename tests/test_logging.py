"""Tests for logging setup."""

import logging

from thefrontoffice.config.logging import setup_logging


def test_root_level_follows_the_configured_setting() -> None:
    setup_logging()
    assert logging.getLogger().level == logging.INFO


def test_repeated_calls_do_not_stack_handlers() -> None:
    """main() and the Streamlit entry point both call this."""
    setup_logging()
    before = len(logging.getLogger().handlers)
    setup_logging()
    assert len(logging.getLogger().handlers) == before


def test_noisy_third_party_loggers_are_quieted() -> None:
    """yahoofantasy and urllib3 at INFO would bury the report in request logs."""
    setup_logging()
    for name in ("yahoofantasy", "urllib3", "oauthlib", "requests_oauthlib"):
        assert logging.getLogger(name).level == logging.WARNING
