# The Front Office

[![CI](https://github.com/abhishekbabu/the-front-office/actions/workflows/ci.yml/badge.svg)](https://github.com/abhishekbabu/the-front-office/actions/workflows/ci.yml)

AI-powered NBA fantasy general manager for Yahoo category leagues.

Scouts the waiver wire, evaluates trades, and answers follow-up questions about
both — grounding every prompt in live league state, real NBA box scores, and the
remaining schedule.

## Tech Stack

**Application** (`src/the_front_office/`, Python managed with `uv`)
- Interactive slash-command REPL in `main.py`
- `scout/` and `trade/` orchestrate a run: gather league state, build a prompt, return a validated report
- `services/context_builder.py` renders players into the prompt lines both engines share
- `render.py` turns reports into terminal output; `exceptions.py` holds the `FrontOfficeError` hierarchy services raise
- `config/` holds validated settings (`pydantic-settings`) and the prompt templates

**External clients** (`src/the_front_office/clients/`)
- **Yahoo Fantasy** via `yahoofantasy` — OAuth2, rosters, matchups, and hand-built player queries that sort free agents by an individual stat category
- **NBA.com** via `nba_api` — one full-season `LeagueGameLog` call bucketed by player, cached in `.nba_cache.json`, with `tenacity` retries classified by error type
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
| `/scout` | Morning Scout Report — AI waiver wire analysis for the current matchup |
| `/trade <text>` | Evaluate a trade, e.g. `/trade Give LeBron James, Get Jayson Tatum` |
| `/rosters` · `/my-roster` | Team rosters |
| `/matchup` | Current matchup score and category breakdown |
| `/help` · `/quit` | — |

The web UI covers the same ground: a Scout page, a Trade page, and a team view
with the matchup category table and roster. Both render the same validated
`ScoutReport` and `TradeVerdict` models — the CLI through `render.py`, the UI
through `ui/app.py`.

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
PR, plus `uv sync --locked` so a dependency change that skipped `just lock`
cannot land. If `just check` passes locally it passes in CI.

Tests are hermetic — no network, no credentials, no cache file on disk. Engines
take their collaborators by keyword, so `tests/conftest.py` fakes stand in for
Yahoo, NBA and Gemini. Anything hitting a live API is marked
`@pytest.mark.integration` and deselected by default.

## Architecture Notes

**Category-league specific.** Prompts assume a 9-cat league and encode the
strategy: target close categories, don't chase blowouts, a 5-4 win counts the
same as 9-0. Points and dynasty leagues are out of scope.

**One set of models, two front ends.** The engines return validated
`ScoutReport` / `TradeVerdict` and know nothing about presentation, so the CLI
and the Streamlit UI are interchangeable renderers over the same data.

**Reports are typed, not prose.** Gemini returns `ScoutReport` and `TradeVerdict`
as response schemas, so a model that ignores the requested shape fails loudly
instead of producing something unrenderable. A schema cannot be combined with
the Google Search tool, so the trade path — which needs live injury news — keeps
search and structures its prose in a second Flash pass.

**Services raise, callers render.** No service returns `None`, `[]`, or an error
string to signal failure; those are indistinguishable from real results. An
empty list is a valid answer (no search matches); a failed request is not.

**Two caches, two invalidation strategies.** The NBA schedule is TTL-based (24h).
The league game log invalidates at 1:00 AM and 3:00 PM **Pacific** — after games
end, before they start — so a report never mixes stale box scores into a live
matchup. Both are anchored to `America/Los_Angeles` with timestamps stored as
UTC, so behaviour is identical wherever the machine is.

**Remaining-game counts are zone-independent.** The matchup *window* test uses
the NBA game-date label (what Yahoo's matchup dates also mean); the
*already-played* test uses the true tip-off instant in UTC. "Remaining" means not
yet started. The status filter still runs, since a cached schedule can be 24h old.

**Rate limiting is deliberate.** `nba_api` calls are spaced by
`settings.nba_api_delay` and retried only on transient failures — timeouts, 5xx,
and the non-JSON body stats.nba.com serves when throttling. A 4xx or a changed
payload shape fails immediately rather than burning the budget.

**Platform.** Runs on macOS, Linux and Windows. `pyreadline3` and `tzdata` are
installed only on Windows; `main()` reconfigures stdout to UTF-8 so redirected
output survives a cp1252 locale; `.gitattributes` pins `eol=lf`.

## Security

Never commit `.env`, `.yahoofantasy`, or `.nba_cache.json` — all three are
gitignored, and `detect-private-key` runs as a pre-commit hook. Credentials are
read only through `AppSettings`.
