# The Front Office - Project Rules

## Project Overview
The Front Office is an AI-powered NBA fantasy sports assistant that provides waiver wire analysis, trade recommendations, and strategic insights using Yahoo Fantasy API and Google Gemini AI.

## Code Style & Standards

### Type Safety
- **ALWAYS** run `pyrefly check` before committing
- **AVOID** using `Any`. Use specific types from libraries or `object` if truly generic.
- Add type hints to all function signatures
- Use builtin generics (`list[str]`, `dict[str, int]`) and PEP 604 unions (`str | None`), not `typing.List`/`Dict`/`Optional` — enforced by ruff's `UP` rules
- Handle `None` values explicitly with assertions or conditional checks
- Untyped third-party libraries need no per-import marker; suppressions live in `pyrefly.toml`

### Metadata & Documentation
- **ALWAYS** update `README.md`, `project_spec.md`, `pyproject.toml`, and other metadata files before committing new changes.
- Ensure the "Current Status" and "Roadmap" in `README.md` reflect the latest accomplishments.
- Keep the `Technical Stack` and `Project Structure` accurate.

### Import Hygiene
- Run `ruff check src/ --fix` — it removes unused imports (F401) and sorts import groups (I001) for you.
- Imports are grouped standard library / third-party / local, enforced by ruff's isort rules.
- Avoid wildcard imports (`from module import *`) and relative imports (`from .x import y`, banned by TID252).

### Project Structure
```
the-front-office/
├── src/the_front_office/     # All production code goes here
│   ├── clients/              # External API wrappers (Gemini, Yahoo, NBA)
│   ├── config/               # Configuration layer (constants, settings)
│   ├── scout/                # Scout feature (AI waiver analysis)
│   │   ├── __init__.py       # Re-exports Scout class
│   │   └── engine.py         # Scout orchestrator
│   └── main.py               # Interactive REPL entry point
├── tests/                    # Hermetic unit tests (pytest)
├── justfile                  # Task runner (just check / test / run)
├── Brewfile                  # System tooling (just, uv)
├── uv.lock                   # Pinned dependency graph
├── .agent/rules/rules.md     # Project configuration and rules
├── pyrefly.toml              # Type checking config
└── pyproject.toml            # Project metadata & dependencies
```

### Module Organization
- Keep modules focused and single-purpose
- Use `__init__.py` to expose public APIs
- Place temporary/debug scripts in `scripts/` directory (not project root)
- Never commit temporary exploration files to main codebase

### Dependencies
- **Production**: Add to `dependencies` in `pyproject.toml`
- **Development**: Add to `[dependency-groups] dev` in `pyproject.toml`
- **Anything imported directly gets declared directly** — never rely on a transitive dependency,
  even one that is certain to be installed. `requests` and `pydantic` are declared for this reason.
- **System tooling** (CLIs, not Python packages) goes in the `Brewfile`
- Bound both ends: `package>=X.Y.Z,<NEXT_MAJOR`, then run `just lock`
- Install with `just install` / `just lock` (`uv sync`), never `uv pip install` — only `uv sync`
  honours `uv.lock`. Verify with `just verify-lock`.

### Environment Variables
- Store secrets in `.env` (never commit)
- Document all env vars in `.env.template`
- Declare every env var as a typed field on `AppSettings` (`config/settings.py`); pydantic-settings
  loads and validates them, so a malformed value fails at startup with a readable error
- Read config through the `settings` singleton — never `os.getenv` at a call site

### Error Handling
- Use specific exception types, not bare `except:`
- **Services never signal failure by return value.** No `None`, no `[]`, no `"❌ ..."` string — a caller
  cannot tell those apart from a real result. Raise a `FrontOfficeError` subclass from
  `the_front_office.exceptions` instead.
- An empty list is a valid *answer* (no search matches); a failed request is not — those raise.
- Only `main.py` renders errors to the user. It catches `FrontOfficeError` and prints the message.
- Log with `logger.error()` before raising; use `raise ... from e` to keep the cause.
- Never expose API keys or sensitive data in error messages
- **No `print()` outside `main.py`** — library code uses a module-level logger

### Git Workflow
- **Feature branches**: `feature/descriptive-name`
- **Commit format**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- **Pull Requests**: Required for all changes to `main`
- **Branch cleanup**: Delete feature branches after merging

### Testing
- Place tests in `tests/`, mirroring source structure (`tests/test_scout.py` for `scout/engine.py`).
- The default suite must stay **hermetic**: no network, no credentials, no `.nba_cache.json` on disk.
  Seed state directly (`NBAClient.__new__` + a hand-built `_cache_data`) rather than letting `__init__` read disk.
- Anything touching a live API gets `@pytest.mark.integration`; it is deselected by default via `addopts`.
- Run `pytest` before pushing — also enforced by pre-commit.

## API Integration

### Yahoo Fantasy API
- Use `yahoofantasy` SDK for all API calls
- Token stored in `.yahoofantasy` (gitignored)
- Handle pagination quirks in `League.players()` method
- Use `status='A'` for available players

### Google Gemini AI
- Use `google-genai` package (NOT deprecated `google-generativeai`)
- **Model Selection**:
    - Use `gemini-2.5-pro` for strategy, analysis, and natural language insights.
    - Use `gemini-2.5-flash` only for large-scale data parsing tasks where high speed is required.
    - **AVOID** using preview versions (e.g., `-preview`) unless explicitly required.
- Check for `GOOGLE_API_KEY` before making API calls
- Provide fallback messages when API key is missing

## Code Quality Checklist
Before committing:
- [ ] `ruff check src/` and `ruff format --check src/` pass
- [ ] `pyrefly check` passes
- [ ] `pytest` passes
- [ ] (all three run automatically if `pre-commit install` has been run)
- [ ] No debug print statements (use `logger` instead)
- [ ] No hardcoded credentials
- [ ] Updated `pyproject.toml` if dependencies changed
- [ ] Updated `.env.template` if new env vars added
- [ ] Type hints on all new functions
- [ ] Docstrings for public APIs

## Common Patterns

### Logging
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Informational message")
logger.warning("Warning message")
logger.error("Error message")
```

### Type Annotations
```python
def fetch_players(league, count: int = 20) -> list[object]:
    players: list[object] = league.players(status="A")
    return players[:count]
```

### Environment Variables
```python
from the_front_office.config.settings import settings

if settings.gemini_api_key is None:
    ...  # degrade gracefully; --mock must work without credentials
```

## AI Assistant Guidelines
When working on this project:
1. Maintain the established package structure
2. Run type checking after code changes
3. Use feature branches for all changes
4. Create PRs with descriptive titles and bodies
5. Keep commits atomic and well-described
6. Never commit secrets or tokens
7. **ALWAYS** run Python commands through the project venv. Prefer the `justfile` recipes (`just check`, `just test`, `just run`); they pin the interpreter so no activation step is needed.
