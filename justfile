set shell := ["bash", "-euo", "pipefail", "-c"]

py := ".venv/bin/python"
bin := ".venv/bin"

# List available recipes
default:
    @just --list

# ============================================================================
# Setup
# ============================================================================

# Create the venv and install locked dependencies + git hooks
install:
    uv venv --python 3.10
    uv pip install -e ".[dev]"
    {{bin}}/pre-commit install
    @echo "✅ Ready. Copy .env.template to .env and fill in your credentials."

# Re-resolve the lockfile after changing dependencies in pyproject.toml
lock:
    uv lock
    uv pip install -e ".[dev]"

# ============================================================================
# Quality
# ============================================================================

# Run every check the pre-commit hooks run (lint, format, types, tests)
check: lint typecheck test
    @echo "✅ All checks passed."

# Lint and auto-fix, then format
fmt:
    {{bin}}/ruff check src/ tests/ --fix
    {{bin}}/ruff format src/ tests/

# Lint without fixing — fails on any finding
lint:
    {{bin}}/ruff check src/ tests/
    {{bin}}/ruff format --check src/ tests/

# Type check
typecheck:
    {{bin}}/pyrefly check

# Run the hermetic test suite
test *args:
    {{bin}}/pytest {{args}}

# Run the tests that hit live APIs (needs credentials)
test-integration:
    {{bin}}/pytest -m integration

# Run all hooks against every file, as pre-commit would
hooks:
    {{bin}}/pre-commit run --all-files

# ============================================================================
# Run
# ============================================================================

# Start the interactive CLI
run:
    {{py}} -m the_front_office.main

# ============================================================================
# Housekeeping
# ============================================================================

# Delete caches and build artefacts (leaves .env and auth tokens alone)
clean:
    rm -rf .ruff_cache .pytest_cache .mypy_cache .pyrefly_cache
    find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
    @echo "✅ Cleaned."

# Delete the cached NBA stats/schedule so the next run refetches
clean-nba-cache:
    rm -f .nba_cache.json
    @echo "✅ NBA cache cleared."
