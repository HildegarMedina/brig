#!/usr/bin/env bash
# Install development dependencies and activate the Git hook for this clone.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install it using https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

uv sync --locked
uv run --locked pre-commit install
uv run --locked pre-commit run --all-files
