# The Front Office

[![CI](https://github.com/abhishekbabu/the-front-office/actions/workflows/ci.yml/badge.svg)](https://github.com/abhishekbabu/the-front-office/actions/workflows/ci.yml)

AI-powered fantasy sports general manager. NBA on Yahoo, NFL on Sleeper, Fantasy
Premier League on the official game.

Scouts the waiver wire, sets lineups, evaluates trades, and answers follow-up
questions about any of it — grounding every prompt in live league state, real
stats and the fixtures ahead.

## Tech Stack

**Layout** (`src/the_front_office/`, Python managed with `uv`) — ports and adapters,
with dependencies pointing strictly inward:

```text
domain/       models and ports. Imports nothing else in the package.
application/  use cases over ports: ScoutEngine, TradeEngine.
adapters/
  inbound/    drivers — the CLI and the Streamlit UI.
  outbound/   driven — platform clients, the language model, and the
              per-sport providers implementing SportProvider.
bootstrap.py  the composition root: the only module naming a concrete
              implementation. Registers sports and wires engines.
```

No adapter is named anywhere in `domain/` or `application/`; the engines take an
`AnalysisModel` port rather than a vendor client.

**Outbound adapters** (`src/the_front_office/adapters/outbound/`)
- **Yahoo Fantasy** via `yahoofantasy` — OAuth2, rosters, matchups, and hand-built player queries that sort free agents by an individual stat category
- **NBA.com** via `nba_api` — one full-season `LeagueGameLog` call bucketed by player for recent form (L5/L10/L15), cached in `.nba_cache.json`, with `tenacity` retries classified by error type
- **Sleeper** — public and auth-free, and used by both sports: football leagues, rosters, matchups and weekly projections; NBA per-game projections summed into category totals for the matchup period. Cached in `.sleeper_cache.json`
- **Fantasy Premier League** — public and auth-free, and the only platform here that is also its own stats provider: one `bootstrap-static` call carries the squad, the prices, the game's own `ep_next` projection and Opta expected goals. Cached in `.fpl_cache.json`
- **Gemini** via `google-genai` — `gemini-2.5-pro` for analysis, `gemini-2.5-flash` for parsing

**Tracing** — OpenTelemetry via `logfire`, configured in
[`config/telemetry.py`](src/the_front_office/config/telemetry.py) and nowhere else.
Everything worth measuring happens inside a library, so `requests`, `google-genai`
and `pydantic` are auto-instrumented and no span is opened by hand — `domain/` and
`application/` never learn that telemetry exists. The standard-library logging the
app already does is bridged, so cache hits and retry warnings arrive as events on
the span that caused them. Without `LOGFIRE_TOKEN` nothing is exported and no
network call is made.

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
| `FPL_ENTRY_ID` | for FPL | — | The number in the URL of your own points page. FPL has no username lookup |
| `YAHOO_MAX_WEEKLY_ADDS` | no | `3` | Integer ≥ 0; drives the scout's add budget |
| `LOGFIRE_TOKEN` | no | — | A write token from a [Logfire](https://logfire.pydantic.dev) project. Omit and nothing is exported |
| `LOGFIRE_ENVIRONMENT` | no | `local` | Separates traces from a laptop and a deployed run in one project |
| `LOGFIRE_CAPTURE_PROMPTS` | no | `false` | Sends prompt and completion **text**. Off deliberately — a prompt carries your roster, leagues and FPL entry id |
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
| `/trade [sport] <text>` | Evaluate a trade, e.g. `/trade nfl Give Bijan, Get Puka`. The sport is optional when only one supports trades. FPL is excluded — its managers transfer against the market rather than trading each other |
| `/help` · `/quit` | — |

Add `--mock` to `/scout` or `/trade` to swap Gemini for canned responses and
exercise the report path without spending tokens. League data stays live.

The web UI covers the same ground with a sport picker in the sidebar. Both
front ends render the same validated models.

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

`just --list` for the full catalog.

Agent-facing rules are in [`AGENTS.md`](AGENTS.md), with shared skills under
[`.agents/skills/`](.agents/skills/). `CLAUDE.md` beside any `AGENTS.md` is a
symlink to it, and `.claude/skills` and `.agent/rules/rules.md` are symlinks
too — one source of truth, discovered by each tool at the path it expects.
`just check-agents` enforces that.

CI runs the same `just` recipes on Linux, macOS and Windows for every push and
PR, on the Python version `.python-version` pins plus one newer leg, with
`uv sync --locked` so a dependency change that skipped `just lock` cannot land.
If `just check` passes locally it passes in CI.

Tests are hermetic — no network, no credentials, no cache file on disk. Engines
take their collaborators by keyword, so `tests/conftest.py` fakes stand in for
Yahoo, NBA and Gemini. Anything hitting a live API is marked
`@pytest.mark.integration` and deselected by default.

## Project Layout

```text
the-front-office/
├── src/the_front_office/
│   ├── domain/            # models + ports (pure — imports nothing else here)
│   ├── application/       # scouting and trading use cases, over ports
│   ├── adapters/
│   │   ├── inbound/       # drivers: cli/, web/
│   │   └── outbound/      # driven: llm/, platforms/, sports/
│   ├── bootstrap.py       # composition root: sport registry + engine wiring
│   └── config/            # validated settings + prompt templates
├── tests/                 # hermetic pytest suite
├── AGENTS.md              # agent-facing rules (CLAUDE.md symlinks to it)
├── .agents/skills/        # shared agent skills
├── Brewfile               # system tooling (just, uv)
├── justfile               # task runner
├── pyproject.toml         # package metadata, dependencies, tool config
└── uv.lock                # pinned dependency graph
```

## Security

Never commit `.env`, `.yahoofantasy`, or any `.*_cache.json` — all of them are
gitignored, and `detect-private-key` runs as a pre-commit hook. Credentials are
read only through `AppSettings`.
