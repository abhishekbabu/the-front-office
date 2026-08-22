# The Front Office — Agent Rules

Project overview, setup, architecture and commands live in [`README.md`](../../README.md).
This file is only the rules an agent needs that the README does not already state.

## Before committing

`just check` (lint, format, types, tests, 95% coverage floor) must pass. The
pre-commit hooks run the same gates, so a commit that skips them will fail anyway.

Update `README.md` in the same commit when behaviour, commands, dependencies or
environment variables change. It is the only prose documentation — do not add
new doc files.

## Hard rules

**Errors.** Services never signal failure by return value — no `None`, no `[]`,
no `"❌ ..."` string, all of which a caller cannot tell from a real result.
Raise a `FrontOfficeError` subclass from `the_front_office.exceptions`. An empty
list is a valid *answer* (no search matches); a failed request is not. Only
`main.py` and `ui/` render errors. `raise ... from e`, and log before raising.

**No `print()` outside `main.py` and `ui/`.** Library code uses a module-level
`logger = logging.getLogger(__name__)`.

**Dates and times.** Never use naive `datetime.now()` or `date.today()` for
anything persisted or compared — store aware UTC, convert at the comparison.
NBA-schedule logic is anchored to `PACIFIC` in `clients/nba/client.py`, because
the league schedules by Pacific and a local clock shifts the boundaries by the
machine's offset. `datetime.fromisoformat` cannot parse a trailing `Z` on
Python 3.10 and every NBA timestamp has one, so parse via `_parse_timestamp`.
Keep `GameRecord["date"]` (a game-date label, for window tests) distinct from
`GameRecord["tipoff_utc"]` (a real instant, for has-it-started tests).

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
`st.cache_data` for values). Put computation in `ui/data.py` where it is
testable; `ui/app.py` only lays out widgets. Keep `main()` behind the
`__name__ == "__main__"` guard so the module stays importable.

**Adding a sport.** Implement `SportProvider` in `sports/<sport>/<platform>.py`
(`list_leagues`, `build_context`, `squad_rows`), add a prompt template and a
canned mock report, then add one `SportEntry` to `sports/registry.py`. The CLI,
the UI and the help text pick it up from there — do not name a provider in an
entry point. `is_configured` must be true only when the credentials actually
exist: building a provider may open an OAuth flow, and a user who does not play
that sport must never be made to sit through it. Do not add sport
specifics to `report/`, `render.py` or `ui/` — those are the shared seam. If a
sport needs a field the shared `Move` / `ScoutReport` / `TradeVerdict` lacks,
widen those models rather than forking them. Keep their field names in the
league's own vocabulary, not one sport's: `gains`, not `categories_gained`.

## Testing

Mirror the source layout. The default suite must stay hermetic: no network, no
credentials, no cache file on disk. Engines take their collaborators by keyword
(`Scout(league, ai=..., nba=..., yahoo=...)`) — use the fakes in
`tests/conftest.py` rather than monkeypatching. Anything hitting a live API gets
`@pytest.mark.integration`, which is deselected by default.

New code needs tests in the same commit. Coverage is gated at 95%.

## CI

`.github/workflows/ci.yml` runs `just lint`, `just typecheck` and
`just coverage-gate` on Linux, macOS and Windows, plus the non-duplicated
pre-commit hooks. `.python-version` pins 3.10 — the floor in `requires-python`,
and what pyrefly and ruff target — so CI reproduces local rather than silently
testing a newer interpreter; one extra leg runs 3.13 for forward compatibility. It calls the same recipes you run locally — add a gate to the
`justfile` and CI picks it up, rather than duplicating the command in YAML.

## Git

Feature branches (`feat/`, `fix/`, `chore/`, `test/`), conventional commit
subjects, and a PR into `main` — the `no-commit-to-branch` hook blocks direct
commits. Delete branches after merging.
