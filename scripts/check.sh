#!/usr/bin/env bash
# The same checks as CI (.github/workflows/ci.yml), in a clean environment with only the core + test
# dependencies — so a test that silently needs an extra package fails here, not on GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_PROJECT_ENVIRONMENT=.venv-ci PYTHONUTF8=1
uv sync --no-default-groups --group dev --group test
uv run ruff check src tests
uv run pytest -q
