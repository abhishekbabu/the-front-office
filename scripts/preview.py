"""Serve the real app on its own port, for inspecting the UI.

A verification harness, not a deployment target. It runs the same routes against
the same platforms as `just ui` — the point is to look at what the app actually
renders, so substituting fixtures would only confirm whatever the fixtures were
written to show. Real data is where the awkward cases live: league names with
emoji in them, a preseason week where every projection is zero, a squad of
fifteen rather than a tidy three.

Two differences from `just ui`, both about not disturbing anything:

  * a separate port, so a running `just ui` keeps its own;
  * Mock AI forced on for this process only, so reports render without a model
    and without editing .env. League data stays live either way.

Run with `just preview`.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

PORT = 8100


def main() -> int:
    # Set before the settings singleton is built. The process environment wins
    # over .env, so this leaves the file alone.
    if "--live-ai" not in sys.argv:
        os.environ["MOCK_AI"] = "true"

    import uvicorn

    from the_front_office.adapters.inbound.web.api import create_app

    print(f"\n  Preview on http://127.0.0.1:{PORT}")
    print(f"  Mock AI is {'off — reports will call the model' if '--live-ai' in sys.argv else 'on'}.")
    print("  League data is live either way.\n")
    uvicorn.run(create_app(), host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
