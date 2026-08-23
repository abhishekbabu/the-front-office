"""Authorise this machine with Yahoo, once.

The OAuth2 handshake opens a browser and waits for a click, so it cannot run
inside the web server or anywhere else non-interactive — those paths report that
a token is missing and point here. The token lands in `.yahoofantasy` and is
reused until it is deleted.

Run with `just yahoo-login`.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from the_front_office.adapters.outbound.platforms.yahoo.client import YahooClient  # noqa: E402
from the_front_office.config.logging import setup_logging  # noqa: E402
from the_front_office.domain.errors import FrontOfficeError  # noqa: E402


def main() -> int:
    setup_logging()
    force = "--force" in sys.argv

    if YahooClient._token_exists() and not force:
        print("  Already authorised. Pass --force to replace the cached token.")
        return 0

    print("  A browser window will open — authorise the app there.")
    try:
        YahooClient.login(force=force)
    except FrontOfficeError as e:
        print(f"  ❌ {e}")
        return 1
    print("  ✅ Authorised. The token is cached in .yahoofantasy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
