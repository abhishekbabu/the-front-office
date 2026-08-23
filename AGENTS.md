# The Front Office — Agent Rules

Project overview, setup, architecture and commands live in [`README.md`](README.md).
This file is only the rules an agent needs that the README does not already state.

Skills live in [`.agents/skills/`](.agents/skills/); see [`.agents/AGENTS.md`](.agents/AGENTS.md)
for the index.

## Before committing

`just check` (lint, format, types, tests, 95% coverage floor) must pass. The
pre-commit hooks run the same gates, so a commit that skips them will fail anyway.

Update `README.md` in the same commit when behaviour, commands, dependencies or
environment variables change. Prose documentation lives there and in this file;
do not add new doc files.

## Hard rules

**Errors.** Services never signal failure by return value — no `None`, no `[]`,
no `"❌ ..."` string, all of which a caller cannot tell from a real result.
Raise a `FrontOfficeError` subclass from `domain/errors.py`. An empty list is a
valid *answer* (no search matches); a failed request is not. Only the inbound
adapters render errors. `raise ... from e`, and log before raising.

**No `print()` outside `adapters/inbound/`.** Everything else uses a module-level
`logger = logging.getLogger(__name__)`.

**Dates and times.** Never use naive `datetime.now()` or `date.today()` for
anything persisted or compared — store aware UTC, convert at the comparison.
NBA-schedule logic is anchored to `PACIFIC` in the nba_stats client, because
the league schedules by Pacific and a local clock shifts the boundaries by the
machine's offset. `datetime.fromisoformat` cannot parse a trailing `Z` on
Python 3.10 and every NBA timestamp has one, so parse via `_parse_timestamp`.
Keep `GameRecord["date"]` (a game-date label, for window tests) distinct from
`GameRecord["tipoff_utc"]` (a real instant, for has-it-started tests).

**Naming.** `<Platform>Client` for API clients, `<Platform><Sport>Provider` for
providers, `<Verb>Engine` for use cases, `<What>Error` for domain errors.
Sport-specific constants lead with the sport: `NBA_SCOUT_PROMPT`,
`MOCK_NFL_REPORT`. The word for a set of players a manager owns is **roster**,
everywhere. Test modules mirror the module they cover.

Under `adapters/outbound/sports/<sport>/`, the provider file is named for the
platform that owns the **league** — `nba/yahoo.py`, `nfl/sleeper.py`. Other
platforms a sport reads from are role-named helpers (`projections.py`,
`lineup.py`), never a second file named after a platform.

**Types.** Avoid `Any`; prefer builtin generics and PEP 604 unions, which ruff's
`UP` rules enforce. `missing-attribute` is disabled for modules touching the
yahoofantasy SDK because it sets attributes via `setattr` at runtime — do not
re-enable it there, and do not disable anything else globally.

**Yahoo fetching.** yahoofantasy's persistence is a read-modify-write of one
shared pickle, so never call `_load_or_fetch`/`_save` from a thread pool — only
`make_request` is safe to parallelise. Live-changing data (the scoreboard) needs
an explicit short `persist_ttl`; the default is an hour.

**Chat history is resent every turn.** Seed follow-up chats with a briefing, not
the generation prompt, and say explicitly what was left out.

**Player identity across platforms.** Yahoo and Sleeper share no identifier, so
the NBA projection join is by normalised name (`adapters/outbound/sports/nba/
projections.py`).
Never guess: an ambiguous surname must resolve to nothing rather than to
whichever player was indexed first, and an unmatched player carries no
projection rather than borrowing someone else's.

**AI calls.** `gemini-2.5-pro` for analysis, `gemini-2.5-flash` for parsing and
structuring. Never a `-preview` model. Reports come back as Pydantic models via
a response schema, never as prose to be regex'd. A response schema cannot be
combined with the Google Search tool — that is why the trade path structures its
search-grounded prose in a second Flash pass.

**Dependencies.** Anything imported directly gets declared directly, never
relied on transitively. Bound both ends (`>=X.Y.Z,<NEXT_MAJOR`), then `just lock`.
System CLIs go in the `Brewfile`. Use `just install` / `just lock` (`uv sync`) —
`uv pip install` ignores `uv.lock`.

**Portability.** Never hardcode `.venv/bin/...` or `.venv/Scripts/...` in a
recipe, hook or script; `uv run` resolves it everywhere. No POSIX-only commands
in tooling — the project supports Windows, where no bash is guaranteed. Put
scripts in `scripts/` instead.

**Secrets.** Never commit `.env`, `.yahoofantasy`, or `.nba_cache.json`. Read
config through the `settings` singleton, never `os.getenv` at a call site.

**UI.** Streamlit reruns the whole script on every interaction, so anything
expensive or side-effecting must be cached (`st.cache_resource` for clients,
`st.cache_data` for values). Put computation in the web adapter's `data.py`
where it is testable; the app module only lays out widgets. Keep `main()` behind the
`__name__ == "__main__"` guard so the module stays importable.

**Extract on the second instance.** This app is deliberately shaped so sports
and platforms differ only where they genuinely differ; everything else is
shared. When you find yourself writing something a second time, extract it then
— not on the third. Existing seams:

- `adapters/outbound/platforms/` — infrastructure every platform needs:
  `retry.py` (transient-failure policy), `cache.py` (TTL'd disk cache).
- `adapters/outbound/sports/` — policy every sport needs: `names.py`
  (cross-platform player matching), `trades.py` (resolving a proposal).
- `domain/` — rules that hold regardless of sport or platform.

**Prefer composition to a base class.** The outbound clients share behaviours,
not a shape: one does raw HTTP and three go through different vendor SDKs, and
each caches differently. Shared behaviour is a function you call or a
collaborator you are given, so a client adopts only the parts that apply.

**Layering.** Dependencies point inward only: `domain` imports nothing else in
the package; `application` imports only `domain`; adapters implement ports;
`bootstrap.py` is the one module allowed to name a concrete implementation.
Never import an adapter from `domain/` or `application/` — if an engine needs a
capability, add a port and let `bootstrap` wire it. Engines take their
collaborators as required arguments rather than constructing defaults.

**Adding a sport.** See the `adding-a-sport` skill. In short: a provider under
`adapters/outbound/sports/`, a prompt template, a canned mock, one `SportEntry`
in `bootstrap.py`. Never name a provider in an entry point, and never put sport
specifics in `domain/`, `application/` or the inbound adapters. If a sport needs
a field the shared models lack, widen them — and name it in the league's own
vocabulary, `gains` rather than `categories_gained`.

## Testing

Mirror the source layout. The default suite must stay hermetic: no network, no
credentials, no cache file on disk. Engines and providers take their collaborators
by keyword — use the fakes in `tests/conftest.py` rather than monkeypatching. Anything hitting a live API gets
`@pytest.mark.integration`, which is deselected by default.

New code needs tests in the same commit. Coverage is gated at 95%.

## CI

CI runs the same `just` recipes you run locally on Linux, macOS and Windows, so
adding a gate to the `justfile` extends CI too. `.python-version` pins 3.10 —
the floor in `requires-python`, and what pyrefly and ruff target — with one
extra leg on 3.13 for forward compatibility.

## Agent documentation

`AGENTS.md` is the source of truth. `CLAUDE.md` beside it is a **symlink** —
never edit it, and never replace it with a real file; two real files drift and
each tool reads a different one. Skills live in `.agents/skills/<name>/SKILL.md`
with `name` and `description` frontmatter, discovered by Claude through the
`.claude/skills` symlink and by Antigravity through `.agent/rules/rules.md`.

Keep every `AGENTS.md` under 200 lines. `just check-agents` enforces all of it.

## Git

Feature branches (`feat/`, `fix/`, `chore/`, `test/`), conventional commit
subjects, and a PR into `main` — the `no-commit-to-branch` hook blocks direct
commits. Delete branches after merging.
