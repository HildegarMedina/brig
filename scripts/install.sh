#!/usr/bin/env bash
# Install Brig and prepare its Docker dependencies for the current host user.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(id -u)" == "0" ]]; then
    echo "Run this installer as your regular user, without sudo. System installation steps use sudo when needed." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install it using https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

source "$repo_root/scripts/docker_dependencies.sh"
ensure_docker
uv tool install --reinstall "$repo_root"
echo "Brig installed. If brig is not on PATH, run 'uv tool update-shell' and open a new terminal."
