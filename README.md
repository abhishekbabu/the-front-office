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

**Inbound adapters** — a slash-command CLI, and a FastAPI service that returns the
domain models directly: `ScoutReport` *is* a route's response schema, so there is no
second representation of a report to keep in step. It also serves the built UI from
`web/dist`, so one process on one port covers both.

**Outbound adapters** (`src/the_front_office/adapters/outbound/`)
- **Yahoo Fantasy** via `yahoofantasy` — OAuth2, rosters, matchups, and hand-built player queries that sort free agents by an individual stat category. Responses are cached in `.yahoo_cache.json` rather than the SDK's own store
- **NBA.com** via `nba_api` — one full-season `LeagueGameLog` call bucketed by player for recent form (L5/L10/L15), cached in `.nba_cache.json`, with `tenacity` retries classified by error type
- **Sleeper** — public and auth-free, and used by both sports: football leagues, every roster in them, matchups and weekly projections; the real-world season schedule, season totals and the league's transaction feed; NBA per-game projections summed into category totals for the matchup period. Cached in `.sleeper_cache.json`
- **Fantasy Premier League** — public and auth-free, and the only platform here that is also its own stats provider: one `bootstrap-static` call carries the squad, the prices, the game's own `ep_next` projection and Opta expected goals, with per-player season history, mini-league tables and fixtures alongside. Cached in `.fpl_cache.json`
- **Gemini** via `google-genai` — `gemini-2.5-pro` for analysis, `gemini-2.5-flash` for parsing

**Tracing** — OpenTelemetry via `logfire`, configured in
[`config/telemetry.py`](src/the_front_office/config/telemetry.py) and nowhere else.
Everything worth measuring happens inside a library, so `requests`, `google-genai`
and `pydantic` are auto-instrumented and no span is opened by hand — `domain/` and
`application/` never learn that telemetry exists. The standard-library logging the
app already does is bridged, so cache hits and retry warnings arrive as events on
the span that caused them. Without `LOGFIRE_TOKEN` nothing is exported and no
network call is made.

**Web UI** (`web/`) — React 19, Vite, Tailwind v4 and Radix primitives, served by
FastAPI. Shared pieces live in `components/ui/`: cards, badges, a table that
reads its columns off the data, one loading vocabulary, and `IconButton`, whose
single required `label` is both tooltip and accessible name. Animation is
Motion, loaded lazily so the entry bundle stays near 128 kB gzip — `just
check-web` fails if it grows past 140. Color is themed in two orthogonal dimensions: a palette (`data-theme` on
`<html>`) and light/dark (`color-scheme`, driven by a class), so every token is a
single `light-dark(light, dark)` declaration and no component branches on either.
Status colors are shared across palettes rather than re-themed, and chosen so
pass/fail reads as a warm/cool contrast that survives red-green color blindness.

**Tooling** — `ruff`, `pyrefly`, `pytest`, `pre-commit`, `just` for Python;
`tsc`, `vitest` and `pnpm` for the UI. Every Python recipe runs through `uv run`,
so the same commands work on macOS, Linux and Windows.

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

The UI's **Settings** page writes `.env` directly, so a fresh machine can be
configured without opening an editor. Secrets are write-only there: the server
reports whether one is set, never what it is. Saving re-reads configuration into
the running process, so a sport becomes available without a restart.

**On a second machine**, copy `.env` across by hand — the four secrets
(`YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, `GOOGLE_API_KEY`, `LOGFIRE_TOKEN`)
belong in a password manager, not in this repo, which is public. Then run
`just doctor`, which names every variable the app reads, reports each as present
or absent without echoing a secret, and flags keys nothing will pick up —
`AppSettings` ignores what it does not recognize, so a mistyped key is silent.

Do **not** copy `.yahoofantasy`: refresh-token rotation means two machines
sharing one token can invalidate each other, and re-authenticating is a single
browser flow. Do not copy `.nba_cache.json`, `.sleeper_cache.json`,
`.fpl_cache.json` or `.yahoo_cache.json` either — they are derived, expiring,
and one holds a ~14MB player catalog.

### Environment

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `YAHOO_CLIENT_ID` | yes | — | From your Yahoo developer app |
| `YAHOO_CLIENT_SECRET` | yes | — | From your Yahoo developer app |
| `GOOGLE_API_KEY` | no | — | Omit and the app simply offers no analysis |
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
just ui     # build the UI and serve it at http://localhost:8000
just run    # interactive CLI
```

For UI work, run the two halves separately so the front end hot-reloads:

```bash
just api    # FastAPI on :8000, reloading on change
just web    # Vite on :5173, proxying /api to the above
```

To look at the finished thing:

```bash
just preview   # the real app on its own port, so `just ui` keeps :8000
just shots     # screenshot every view into web/.shots (starts its own preview)
```

`preview` runs the same routes against the same platforms as `just ui` — the
point is to see what the app actually renders, so substituting fixtures would
only confirm whatever the fixtures were written to show. Real data is where the
awkward cases are: a league in a format the code forgot to read, a preseason
week where every projection is zero, a fifteen-man squad rather than a tidy
three. `shots` drives it with Playwright and reports any console errors, which a
screenshot of a blank panel otherwise hides.

NBA needs one interactive step first:

```bash
just yahoo-login    # opens a browser; token cached in .yahoofantasy and reused
```

It is separate because the handshake blocks on a browser click, which a web
request handler cannot do — so every non-interactive path reports a missing
token instead of trying to obtain one.

The handshake is implemented in
[`platforms/yahoo/oauth.py`](src/the_front_office/adapters/outbound/platforms/yahoo/oauth.py)
rather than delegated to the `yahoofantasy` CLI, which exchanges the code
against `redirect_uri="oob"` after authorizing against a different one. RFC 6749
requires the two to match; Yahoo answers the mismatch with a token that
authenticates and carries no grant, so every endpoint returns 403 instead of
401. The browser will warn about the self-signed localhost certificate the
callback is served with — that is expected, and Yahoo only accepts an `https`
redirect.

**Yahoo reviews every application before granting Fantasy Sports API access.**
Creating the app and ticking Fantasy Sports → Read is necessary but not
sufficient; apply at [sports.yahoo.com/developer/access](https://sports.yahoo.com/developer/access/),
where personal single-league use is an accepted category. Until approved, the
login succeeds and every Fantasy endpoint returns 403 — including ones needing
no user permission, which is how this is told apart from a consent problem. An
invalid token would return 401.

Your Yahoo app must also have **API Permissions → Fantasy Sports → Read**, *saved*.
Yahoo fixes a token's grant at the moment you authorize, from whatever
permissions were saved then — so a token minted before that is accepted and
permitted nothing, answering 403 (not 401) on every endpoint including ones
needing no permission at all. A refresh cannot widen a grant, so the only fix is
`just yahoo-login --force`. The login verifies itself and says so rather than
reporting success on an inert token.

| Command | Description |
|---------|-------------|
| `/leagues` | Every league you are in, per sport |
| `/roster [sport]` | Your squad |
| `/scout [sport]` | Analyze a week. No sport runs every configured one |
| `/trade [sport] <text>` | Evaluate a trade, e.g. `/trade nfl Give Bijan, Get Puka`. The sport is optional when only one supports trades. FPL is excluded — its managers transfer against the market rather than trading each other |
| `/help` · `/quit` | — |

`GOOGLE_API_KEY` is optional. Without it the app has no analysis to offer, so
nothing that needs a model is shown — no report, no trade evaluation, no
follow-up chat. Everything read from the platforms works exactly as before.
Adding a key makes those appear on the next request; nothing explains their
absence, because from the outside there is nothing missing.

The web UI opens on a league picker and splits into three views. **This week**
is the matchup: both lineups side by side, the fixtures behind them, and the
changes the projections already imply — all read or computed from league state,
so it is complete before anything is asked of a model. **My team** is the squad
in more depth, and any player opens. **Report** is the analysis, which exists
only when a `GOOGLE_API_KEY` does.

Commands and views are hidden rather than disabled when they cannot work, so
the app is smaller without credentials and never explains an absence.

Both drop you into a follow-up chat afterwards; press Enter on an empty line to
move on.

## Development

```bash
just doctor             # what this machine is configured for; flags typo'd .env keys
just check              # lint + format + types + tests + 95% coverage floor (Python)
just check-web          # typecheck + tests (UI)
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
A separate `web` job typechecks, tests and builds the UI with
`pnpm install --frozen-lockfile`, the same guarantee on that side.
If `just check` and `just check-web` pass locally they pass in CI.

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
├── web/                   # React UI: src/{components,panels,themes,lib}
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
