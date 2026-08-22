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

    # ── Yahoo ───────────────────────────────────────────────────────────
    yahoo_client_id: str | None = None
    yahoo_client_secret: str | None = None
    yahoo_redirect_uri: str = "https://localhost:8080"
    yahoo_token_file: str = ".yahoofantasy"
    yahoo_max_weekly_adds: int = Field(default=3, ge=0)

    # ── Scouting ────────────────────────────────────────────────────────
    default_free_agent_count: int = Field(default=20, gt=0)
    report_free_agent_limit: int = Field(default=15, gt=0)
    nba_api_delay: float = Field(default=4.0, ge=0.0)
    """Seconds between nba_api calls — the project spec requires a delay to avoid IP blocks."""
    nba_cache_file: str = ".nba_cache.json"
    """Unified cache for all NBA data (stats + schedule)."""

    # ── Logging ─────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        """Accept `log_level=debug` in .env without forcing the caller to shout."""
        return v.upper() if isinstance(v, str) else v


settings = AppSettings()
