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

## Testing

Mirror the source layout. The default suite must stay hermetic: no network, no
credentials, no cache file on disk. Engines take their collaborators by keyword
(`Scout(league, ai=..., nba=..., yahoo=...)`) — use the fakes in
`tests/conftest.py` rather than monkeypatching. Anything hitting a live API gets
`@pytest.mark.integration`, which is deselected by default.

New code needs tests in the same commit. Coverage is gated at 95%.

## Git

Feature branches (`feat/`, `fix/`, `chore/`, `test/`), conventional commit
subjects, and a PR into `main` — the `no-commit-to-branch` hook blocks direct
commits. Delete branches after merging.
