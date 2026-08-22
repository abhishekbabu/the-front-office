# The Front Office

[![CI](https://github.com/abhishekbabu/the-front-office/actions/workflows/ci.yml/badge.svg)](https://github.com/abhishekbabu/the-front-office/actions/workflows/ci.yml)

AI-powered fantasy sports general manager. NBA on Yahoo, NFL on Sleeper.

Scouts the waiver wire, sets lineups, evaluates trades, and answers follow-up
questions about any of it — grounding every prompt in live league state, real
stats and the fixtures ahead.

## Tech Stack

**Application** (`src/the_front_office/`, Python managed with `uv`)
- `sports/registry.py` — which sports exist and whether each is configured; every entry point reads it
- `sports/<sport>/<platform>.py` — one provider per sport+platform, turning a league into a rendered prompt
- `report/` — the sport-agnostic pipeline: `ScoutEngine` runs any provider through the model and returns a validated `ScoutReport`
- `trade/` — trade evaluation (Yahoo only so far)
- `main.py` (REPL) and `ui/` (Streamlit) — both driven by the registry, neither knows a platform name
- `render.py`, `exceptions.py`, `config/` — shared output, errors and validated settings

**External clients** (`src/the_front_office/clients/`)
- **Yahoo Fantasy** via `yahoofantasy` — OAuth2, rosters, matchups, and hand-built player queries that sort free agents by an individual stat category
- **NBA.com** via `nba_api` — one full-season `LeagueGameLog` call bucketed by player, cached in `.nba_cache.json`, with `tenacity` retries classified by error type
- **Sleeper** — public and auth-free: leagues, rosters, matchups, the 12k-player catalogue, weekly projections and league-wide trending, cached in `.sleeper_cache.json`
- **Gemini** via `google-genai` — `gemini-2.5-pro` for analysis, `gemini-2.5-flash` for parsing

**Tooling** — `ruff`, `pyrefly`, `pytest`, `pre-commit`, `just`. Every recipe and
hook runs tools through `uv run`, so the same commands work on macOS, Linux and Windows.

## Setup

**1. Install the two CLIs.** Python itself is not installed separately — `uv`
provisions an interpreter matching `requires-python`.

```bash
brew bundle                                    # macOS / Linux
winget install --id=astral-sh.uv --id=Casey.Just -e   # Windows
```

**2. Get credentials.** A [Yahoo developer app](https://developer.yahoo.com/apps/)
with Fantasy Sports **Read** permission and redirect URI `https://localhost:8080`,
and a [Gemini API key](https://aistudio.google.com/app/apikey).

**3. Install and configure.**

```bash
just install                 # uv sync + git hooks
cp .env.template .env        # PowerShell: Copy-Item .env.template .env
```

Without `just`: `uv sync && uv run pre-commit install`.

### Environment

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `YAHOO_CLIENT_ID` | yes | — | From your Yahoo developer app |
| `YAHOO_CLIENT_SECRET` | yes | — | From your Yahoo developer app |
| `GOOGLE_API_KEY` | for AI features | — | Omit to run `--mock` only |
| `SLEEPER_USERNAME` | for football | — | Sleeper needs no key or OAuth — just the username |
| `YAHOO_MAX_WEEKLY_ADDS` | no | `3` | Integer ≥ 0; drives the scout's add budget |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` |
| `NBA_API_DELAY` | no | `4.0` | Seconds between nba_api calls |

Each is a validated field on `AppSettings` in
[`config/settings.py`](src/the_front_office/config/settings.py) — a malformed
value fails at startup naming the field, not mid-report.

## Usage

```bash
just ui     # web UI at http://localhost:8501
just run    # interactive CLI
```

First run opens a browser for the Yahoo OAuth2 handshake; the token is cached in
`.yahoofantasy` and reused.

| Command | Description |
|---------|-------------|
| `/scout [sport]` | Scouting report. No sport runs every configured one |
| `/roster [sport]` | Your roster |
| `/leagues` | Every league, per sport |
| `/trade <text>` | Evaluate a trade, e.g. `/trade Give LeBron James, Get Jayson Tatum` (NBA only) |
| `/help` · `/quit` | — |

Add `--mock` to `/scout` or `/trade` to swap Gemini for canned responses and
exercise the report path without spending tokens. League data stays live.

The web UI covers the same ground with a sport picker in the sidebar. Both
front ends render the same validated models — the CLI through `render.py`, the
UI through `ui/app.py`.

`/scout` and `/trade` accept `--mock`, which swaps Gemini for canned responses so
you can exercise the report path without spending tokens. Yahoo stays live —
`--mock` mocks the AI, not the league data. Both drop you into a follow-up chat
afterwards; press Enter on an empty line to move on.

## Development

```bash
just check              # lint + format + types + tests + 95% coverage floor
just fmt                # auto-fix lint findings, then format
just test               # hermetic suite (args pass through: just test "-k scout")
just coverage           # coverage report
just lock               # re-resolve uv.lock after editing pyproject.toml
just clean              # caches and build artefacts
```

`just --list` for the full catalog. Agent-facing rules are in
[`.agent/rules/rules.md`](.agent/rules/rules.md).

CI runs the same `just` recipes on Linux, macOS and Windows for every push and
PR, on the Python version `.python-version` pins plus one newer leg, with
`uv sync --locked` so a dependency change that skipped `just lock` cannot land.
If `just check` passes locally it passes in CI.

Tests are hermetic — no network, no credentials, no cache file on disk. Engines
take their collaborators by keyword, so `tests/conftest.py` fakes stand in for
Yahoo, NBA and Gemini. Anything hitting a live API is marked
`@pytest.mark.integration` and deselected by default.

## Security

Never commit `.env`, `.yahoofantasy`, or `.nba_cache.json` — all three are
gitignored, and `detect-private-key` runs as a pre-commit hook. Credentials are
read only through `AppSettings`.
