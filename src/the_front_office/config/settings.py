"""Central application configuration backed by environment variables.

A single flat Pydantic settings class — field names are snake_case and
pydantic-settings matches them to SCREAMING_SNAKE env vars case-insensitively.
Values are validated at import time, so a malformed .env fails immediately with
a readable error instead of raising somewhere deep in a report run.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/the_front_office/config/settings.py -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class AppSettings(BaseSettings):
    """One field per environment variable, plus static tuning constants."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Gemini ──────────────────────────────────────────────────────────
    # Optional: absent means AI features degrade to a clear message, and
    # `--mock` still works without any credentials at all.
    gemini_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    default_model: str = "gemini-2.5-pro"

    mock_ai: bool = False
    """Return canned reports instead of calling the model. League data stays live.

    Configuration rather than a per-request flag so one place decides it, and so
    it survives a reload — which is also why every surface shows a badge while
    it is on. A canned report is indistinguishable from a real one on the page.
    """

    # ── Yahoo ───────────────────────────────────────────────────────────
    yahoo_client_id: str | None = None
    yahoo_client_secret: str | None = None
    yahoo_redirect_uri: str = "https://localhost:8080"
    yahoo_token_file: str = ".yahoofantasy"
    yahoo_max_weekly_adds: int = Field(default=3, ge=0)

    # ── Sleeper (fantasy football) ──────────────────────────────────────
    # Sleeper needs no credentials; the username is only used to find leagues.
    sleeper_username: str | None = None
    sleeper_league_id: str | None = None
    """Pin a specific league. Optional — otherwise leagues are discovered from the username."""
    sleeper_cache_file: str = ".sleeper_cache.json"

    # ── Fantasy Premier League ──────────────────────────────────────────
    # FPL needs no credentials, and has no public username lookup — the entry
    # id is the number in the URL of your own points page.
    fpl_entry_id: int | None = Field(default=None, gt=0)
    fpl_cache_file: str = ".fpl_cache.json"

    # ── Scouting ────────────────────────────────────────────────────────
    nba_api_delay: float = Field(default=4.0, ge=0.0)
    """Seconds between nba_api calls — the project spec requires a delay to avoid IP blocks."""
    nba_cache_file: str = ".nba_cache.json"
    """Unified cache for all NBA data (stats + schedule)."""

    # ── Telemetry ───────────────────────────────────────────────────────
    # Optional. Without a token nothing is exported and no network call is
    # made, so a fresh clone and the test suite behave identically to before.
    logfire_token: str | None = None
    logfire_environment: str = "local"
    """Separates traces from a laptop run and a deployed one in the same project."""

    logfire_capture_prompts: bool = False
    """Whether to send prompt and completion text to Logfire.

    Off by default and deliberately so: a prompt carries the user's roster,
    their leagues and their FPL entry id. Timings and token counts answer
    almost every question without any of that leaving the machine.
    """

    # ── Logging ─────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator(
        "gemini_api_key",
        "yahoo_client_id",
        "yahoo_client_secret",
        "sleeper_username",
        "sleeper_league_id",
        "fpl_entry_id",
        "logfire_token",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, v: object) -> object:
        """Treat `KEY=` in .env as absent rather than as an empty string.

        A commented-out or blank line is how people express "I do not use this",
        and `""` is not None — so a plain `is not None` check would report a
        credential as present and the failure would surface later, at the API
        call, instead of at startup.
        """
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        """Accept `log_level=debug` in .env without forcing the caller to shout."""
        return v.upper() if isinstance(v, str) else v


settings = AppSettings()
