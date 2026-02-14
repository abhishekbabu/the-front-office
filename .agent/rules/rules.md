# The Front Office - Project Rules

## Project Overview
The Front Office is an AI-powered NBA fantasy sports assistant that provides waiver wire analysis, trade recommendations, and strategic insights using Yahoo Fantasy API and Google Gemini AI.

## Code Style & Standards

### Type Safety
- **ALWAYS** run `mypy src/the_front_office` before committing
- **AVOID** using `Any`. Use specific types from libraries or `object` if truly generic.
- Add type hints to all function signatures
- Use `List`, `Dict`, `Optional` from `typing` module
- Handle `None` values explicitly with assertions or conditional checks
- Add `# type: ignore[import-untyped]` for untyped third-party libraries

### Metadata & Documentation
- **ALWAYS** update `README.md`, `project_spec.md`, `pyproject.toml`, and other metadata files before committing new changes.
- Ensure the "Current Status" and "Roadmap" in `README.md` reflect the latest accomplishments.
- Keep the `Technical Stack` and `Project Structure` accurate.

### Import Hygiene
- **ALWAYS** remove unused imports. Use `flake8 --select=F401` to check.
- Keep imports organized: standard library first, third-party libraries second, local modules third.
- Avoid wildcard imports (`from module import *`).

### Project Structure
```
the-front-office/
├── src/the_front_office/     # All production code goes here
│   ├── clients/              # External API wrappers (Gemini, Yahoo, NBA)
│   ├── config/               # Configuration layer (constants, settings)
│   ├── main.py               # CLI entry point (League listing, Scout trigger)
│   └── scout.py              # Scout orchestrator (AI waiver analysis)
├── tests/                    # Unit tests (when added)
├── .agent/rules/rules.md     # Project configuration and rules
├── mypy.ini                  # Type checking config
└── pyproject.toml            # Project metadata & dependencies
```

### Module Organization
- Keep modules focused and single-purpose
- Use `__init__.py` to expose public APIs
- Place temporary/debug scripts in `scripts/` directory (not project root)
- Never commit temporary exploration files to main codebase

### Dependencies
- **Production**: Add to `dependencies` in `pyproject.toml`
- **Development**: Add to `[project.optional-dependencies.dev]`
- Always update both `pyproject.toml` AND `requirements.txt`
- Pin minimum versions: `package>=X.Y.Z`

### Environment Variables
- Store secrets in `.env` (never commit)
- Document all env vars in `.env.template`
- Use `python-dotenv` for loading
- Always check for missing env vars and fail gracefully

### Error Handling
- Use specific exception types, not bare `except:`
- Log errors with `logger.error()` before returning fallback values
- Provide user-friendly error messages
- Never expose API keys or sensitive data in error messages

### Git Workflow
- **Feature branches**: `feature/descriptive-name`
- **Commit format**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- **Pull Requests**: Required for all changes to `main`
- **Branch cleanup**: Delete feature branches after merging

### Testing (Future)
- Place tests in `tests/` directory
- Mirror source structure: `tests/test_scout.py` for `src/the_front_office/scout.py`
- Run tests before pushing: `pytest`

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
- [ ] `mypy src/the_front_office` passes
- [ ] No debug print statements (use `logger` instead)
- [ ] No hardcoded credentials
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
from typing import List, Optional, Any

def fetch_players(league, count: int = 20) -> List[Any]:
    players: List[Any] = league.players(status='A')
    return players[:count]
```

### Environment Variables
```python
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
assert api_key is not None, "GOOGLE_API_KEY must be set"
```

## AI Assistant Guidelines
When working on this project:
1. Maintain the established package structure
2. Run type checking after code changes
3. Use feature branches for all changes
4. Create PRs with descriptive titles and bodies
5. Keep commits atomic and well-described
6. Never commit secrets or tokens
