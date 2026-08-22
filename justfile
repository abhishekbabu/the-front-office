# Recipes shell out only to `uv`, which resolves the project venv on every
# platform — no .venv/bin vs .venv\Scripts split, no bash dependency.
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# List available recipes
default:
    @just --list

# ============================================================================
# Setup
# ============================================================================

# Create the venv and install the exact locked dependencies + git hooks
install:
    uv sync
    uv run pre-commit install
    @echo "Ready. Copy .env.template to .env and fill in your credentials."

# Re-resolve the lockfile after changing dependencies in pyproject.toml
lock:
    uv lock
    uv sync

# Verify the environment matches uv.lock exactly, without modifying either
verify-lock:
    uv lock --check
    uv sync --locked --dry-run

# ============================================================================
# Quality
# ============================================================================

# Run every check: lint, format, types, tests, coverage floor
check: lint typecheck coverage-gate
    @echo "All checks passed."

# Lint and auto-fix, then format
fmt:
    uv run ruff check src/ tests/ scripts/ --fix
    uv run ruff format src/ tests/ scripts/

# Lint without fixing — fails on any finding
lint:
    uv run ruff check src/ tests/ scripts/
    uv run ruff format --check src/ tests/ scripts/

# Type check
typecheck:
    uv run pyrefly check

# Run the hermetic test suite
test *args:
    uv run pytest {{args}}

# Test suite with a coverage report
coverage:
    uv run pytest --cov --cov-report=term-missing

# Fail if coverage drops below the agreed floor
coverage-gate:
    uv run pytest --cov --cov-report=term-missing --cov-fail-under=95

# Run the tests that hit live APIs (needs credentials)
test-integration:
    uv run pytest -m integration

# Run all hooks against every file, as pre-commit would
hooks:
    uv run pre-commit run --all-files

# ============================================================================
# Run
# ============================================================================

# Start the interactive CLI
run:
    uv run python -m the_front_office.main

# ============================================================================
# Housekeeping
# ============================================================================

# Delete caches and build artefacts (leaves .env and auth tokens alone)
clean:
    uv run python scripts/clean.py

# Delete the cached NBA stats/schedule so the next run refetches
clean-nba-cache:
    uv run python scripts/clean.py --nba-cache-only
