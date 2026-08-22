# The Front Office

AI-powered NBA fantasy general manager for Yahoo category leagues.

Scouts the waiver wire, evaluates trades, and answers follow-up questions about
both — grounding every prompt in live league state, real NBA box scores, and the
remaining schedule.

## Tech Stack

**Application** (`src/the_front_office/`, Python pinned by [`pyproject.toml`](pyproject.toml), managed with `uv`)
- Interactive slash-command REPL in `main.py` — the only layer that prints
- `scout/` and `trade/` orchestrate a run: gather league state, build a prompt, open a Gemini chat
- `services/context_builder.py` renders players into the prompt lines both engines share
- `exceptions.py` defines the `FrontOfficeError` hierarchy that services raise instead of returning error values
- `config/` holds validated settings (`pydantic-settings`) and the prompt templates

**External clients** (`src/the_front_office/clients/`)
- **Yahoo Fantasy** via `yahoofantasy` — OAuth2, rosters, matchups, and hand-built player queries that sort free agents by an individual stat category
- **NBA.com** via `nba_api` — one full-season `LeagueGameLog` call bucketed by player, cached in `.nba_cache.json`; retries are classified by `tenacity`
- **Gemini** via `google-genai` — `gemini-2.5-pro` for strategy, `gemini-2.5-flash` for parsing trade text

**Tooling**
- `ruff` for lint and format, `pyrefly` for type checking, `pytest` for the hermetic suite
- `pre-commit` runs all three on every commit; `just` is the entry point for everything
- Every recipe and hook invokes tools through `uv run`, so the same commands work on macOS, Linux and Windows

## First-Time Setup

### One-Time Machine Setup

The project needs two CLIs: [`uv`](https://docs.astral.sh/uv/) and
[`just`](https://just.systems). Python itself is not installed separately — `uv`
provisions an interpreter matching `requires-python`.

**macOS / Linux**

```bash
brew bundle
```

**Windows** (PowerShell)

```powershell
winget install --id=astral-sh.uv -e
winget install --id=Casey.Just -e
```

<details>
<summary>Scoop, or no package manager</summary>

```powershell
scoop install uv just
```

Or install `uv` from [astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)
and `just` from [just.systems](https://just.systems/man/en/packages.html).
</details>

### Yahoo Developer App

Create an app at [developer.yahoo.com/apps](https://developer.yahoo.com/apps/) with:

| Setting | Value |
|---------|-------|
| Permissions | Fantasy Sports — **Read** |
| Redirect URI | `https://localhost:8080` |

### Google Gemini API Key

Create a key at [aistudio.google.com](https://aistudio.google.com/app/apikey).

### Install

```bash
just install
cp .env.template .env    # PowerShell: Copy-Item .env.template .env
```

Then fill in your credentials.

`just install` runs `uv sync` (the exact versions in [`uv.lock`](uv.lock)) and
installs the git hooks.

<details>
<summary>Without <code>just</code></summary>

```bash
uv sync
uv run pre-commit install
```

Every recipe in the `justfile` is a thin wrapper over `uv run <tool>`, so any of
them can be run directly this way.
</details>

### Environment

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `YAHOO_CLIENT_ID` | yes | — | From your Yahoo developer app |
| `YAHOO_CLIENT_SECRET` | yes | — | From your Yahoo developer app |
| `GOOGLE_API_KEY` | for AI features | — | Omit to run `--mock` only |
| `YAHOO_MAX_WEEKLY_ADDS` | no | `3` | Integer ≥ 0; drives the scout's add budget |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` |

Every variable is a validated field on `AppSettings` in
[`config/settings.py`](src/the_front_office/config/settings.py) — a malformed
value fails at startup with a message naming the field, not mid-report.

## Daily Development

```bash
just run                # Start the interactive CLI
just check              # Lint + format check + type check + tests
just fmt                # Auto-fix lint findings, then format
just test               # Hermetic test suite (add args: just test "-k scout")
```

First run opens a browser for the Yahoo OAuth2 handshake. The token is cached in
`.yahoofantasy` and reused, so this happens once.

### Slash Commands

| Command | Description |
|---------|-------------|
| `/scout` | Morning Scout Report — AI waiver wire analysis for the current matchup |
| `/trade <text>` | Evaluate a trade in natural language, e.g. `/trade Give LeBron James, Get Jayson Tatum` |
| `/rosters` | Every team roster in the league |
| `/my-roster` | Your roster only |
| `/matchup` | Current matchup score and category breakdown |
| `/help` | List commands |
| `/quit` | Exit |

`/scout` and `/trade` accept `--mock`, which swaps Gemini for canned responses so
you can exercise the report path without spending tokens. Yahoo is still live —
`--mock` mocks the AI, not the league data.

Both drop you into a follow-up chat after the report. Press Enter on an empty
line to move on.

## Common Commands

```bash
# Quality gates
just check              # Everything the git hooks run
just lint               # ruff check + ruff format --check
just fmt                # ruff check --fix + ruff format
just typecheck          # pyrefly
just hooks              # Run all pre-commit hooks against every file

# Tests
just test               # Hermetic suite — no network, no credentials
just test-integration   # Tests that hit live APIs (needs credentials)

# Dependencies
just lock               # Re-resolve uv.lock after editing pyproject.toml
just verify-lock        # Assert the environment matches uv.lock exactly

# Cleanup
just clean              # Caches and build artefacts
just clean-nba-cache    # Force a refetch of NBA stats and schedule
```

Run `just --list` for the full catalog.

## Architecture Notes

**Category-league specific.** Prompts assume a 9-cat league and encode the
strategy: target close categories, do not chase blowouts, a 5-4 win counts the
same as 9-0. Points and dynasty leagues are out of scope.

**Two caches, two invalidation strategies.** The NBA schedule is TTL-based (24h).
The league game log invalidates at 1:00 AM and 3:00 PM PT — after games end and
before they start — so a report never mixes stale box scores into a live matchup.

**Services raise, `main.py` renders.** No service returns `None`, `[]`, or an
error string to signal failure; those are indistinguishable from real results.
They raise a `FrontOfficeError` subclass, and the CLI catches it. An empty list
is a valid answer (no search matches); a failed request is not.

**Rate limiting is deliberate.** `nba_api` calls are spaced by
`settings.nba_api_delay` (4s default) and retried only on transient failures —
timeouts, 5xx, and the non-JSON body stats.nba.com serves when throttling. A 4xx
or a changed payload shape fails immediately rather than burning the budget.

## Testing

```bash
just test
```

The default suite is hermetic: no network, no credentials, no cache file on disk.
Tests seed state directly rather than letting `__init__` read from disk. Anything
touching a live API is marked `@pytest.mark.integration` and deselected by
default.

Coverage targets the logic where a silent error changes a real decision —
volume-weighted FG%/FT%, cache staleness boundaries, remaining-game counting,
retry classification, and command parsing.

## Platform Support

Runs on macOS, Linux and Windows.

**In the application**
- `pyreadline3` is installed only on Windows (`sys_platform == 'win32'`), giving
  the REPL the arrow-key history `readline` provides elsewhere. The import is
  guarded, so a missing module degrades rather than crashes.
- The Yahoo OAuth2 flow shells out to the `yahoofantasy` CLI — `yahoofantasy.exe`
  under `.venv\Scripts\` on Windows, `yahoofantasy` on PATH elsewhere.
  `YahooFantasyClient.login` probes for the former and falls back to the latter.
- `main()` reconfigures stdout/stderr to UTF-8. The UI prints emoji and
  box-drawing characters; Windows sends those to a console as UTF-16 without
  trouble, but falls back to cp1252 as soon as output is redirected to a file or
  pipe, where they would raise `UnicodeEncodeError` and kill the process.
- All filesystem access goes through `pathlib`, and cache reads/writes pass
  `encoding="utf-8"` explicitly rather than inheriting the locale default.

**In the tooling**
- Recipes and hooks call tools through `uv run`, never a `.venv/bin` or
  `.venv\Scripts` path.
- Nothing depends on a POSIX shell — `just clean` is `scripts/clean.py` for
  exactly this reason.
- `.gitattributes` pins `eol=lf` and ruff is configured to match, so a Windows
  checkout cannot produce a diff that only changes line endings.
- `uv.lock` is resolved universally: `pyreadline3` and `colorama` carry
  `sys_platform == 'win32'` markers, so `uv sync` installs the right set.

## Security

- Never commit `.env`, `.yahoofantasy`, or `.nba_cache.json` — all three are gitignored
- `detect-private-key` runs as a pre-commit hook
- Credentials are read only through `AppSettings`; no `os.getenv` at call sites

## Project Layout

```text
the-front-office/
├── src/the_front_office/
│   ├── clients/           # External API wrappers (yahoo, nba, gemini)
│   ├── config/            # Validated settings + AI prompt templates
│   ├── scout/             # Waiver wire orchestrator
│   ├── trade/             # Trade evaluation orchestrator
│   ├── services/          # Shared player-context builder
│   ├── exceptions.py      # Domain exception hierarchy
│   └── main.py            # Interactive REPL
├── tests/                 # Hermetic pytest suite
├── .agent/rules/rules.md  # Agent-facing project rules
├── Brewfile               # System tooling (just, uv)
├── justfile               # Task runner
├── pyproject.toml         # Package metadata, dependencies, tool config
└── uv.lock                # Pinned dependency graph
```

## Roadmap

- [x] Connectivity — OAuth2 and roster sync
- [x] Waiver engine — free agent scan summarised with matchup context
- [x] Interactive CLI
- [x] Trade war room — shutdown risk, roster awareness, live search
- [ ] Dashboard MVP — web-based Morning Scout Report
