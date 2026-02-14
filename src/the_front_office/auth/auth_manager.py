"""
auth_manager.py — Yahoo Fantasy OAuth2 authentication.

Wraps the `yahoofantasy` CLI login flow and provides a ready-to-use
Context object for API calls.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from yahoofantasy import Context  # type: ignore[import-untyped]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIRECT_URI = "https://localhost:8080"
TOKEN_FILE = ".yahoofantasy"


def _load_env() -> None:
    """Load credentials from .env file in the project root."""
    # Walk up from this file to find the project root (where .env lives)
    project_root = Path(__file__).resolve().parents[3]  # src/the_front_office/auth -> root
    env_path = project_root / ".env"

    if not env_path.exists():
        print(
            "⚠️  No .env file found. Copy .env.template → .env and fill in "
            "your Yahoo Client ID and Client Secret."
        )
        sys.exit(1)

    load_dotenv(env_path)

    if not os.getenv("YAHOO_CLIENT_ID") or not os.getenv("YAHOO_CLIENT_SECRET"):
        print(
            "⚠️  YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET must be set in .env"
        )
        sys.exit(1)


def _token_exists() -> bool:
    """Check whether a cached OAuth2 token file already exists."""
    return Path(TOKEN_FILE).exists()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def login(force: bool = False) -> None:
    """Run the yahoofantasy OAuth2 login flow.

    This launches a browser for Yahoo authentication and stores the
    resulting token locally.  Skips login if a valid token already exists
    unless *force* is True.

    Args:
        force: Re-authenticate even if a token file is present.
    """
    _load_env()

    if _token_exists() and not force:
        return

    print("🔐 Starting Yahoo Fantasy OAuth2 login …")
    print(f"   Redirect URI → {REDIRECT_URI}")
    print("   A browser window will open — please authorize the app.\n")

    client_id = os.getenv("YAHOO_CLIENT_ID")
    client_secret = os.getenv("YAHOO_CLIENT_SECRET")

    # These should always be set due to _load_env() check, but mypy needs explicit assertion
    assert client_id is not None, "YAHOO_CLIENT_ID must be set"
    assert client_secret is not None, "YAHOO_CLIENT_SECRET must be set"

    # The yahoofantasy executable is in the same folder as the python executable (Scripts)
    python_dir = Path(sys.executable).parent
    yahoofantasy_bin_path = python_dir / "yahoofantasy.exe"

    if yahoofantasy_bin_path.exists():
        yahoofantasy_bin: str = str(yahoofantasy_bin_path)
    else:
        # Fallback for non-Windows or direct path
        yahoofantasy_bin = "yahoofantasy"

    cmd = [
        str(yahoofantasy_bin),
        "login",
        "--redirect-uri", REDIRECT_URI,
        "--client-id", client_id,
        "--client-secret", client_secret,
        "--listen-port", "8080",
    ]

    try:
        subprocess.run(cmd, check=True)
        print("\n✅ Login successful! Token saved.")
    except subprocess.CalledProcessError as exc:
        print(f"\n❌ Login failed (exit code {exc.returncode}).")
        sys.exit(1)


def get_context() -> Context:
    """Return an authenticated yahoofantasy Context.

    If no token exists yet, triggers the login flow first.
    """
    if not _token_exists():
        login()

    return Context()
