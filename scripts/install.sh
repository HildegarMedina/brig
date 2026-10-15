#!/usr/bin/env bash
# Install Brig and prepare its Docker dependencies for the current host user.
set -Eeuo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
installer_verbose=0
case "${1:-}" in
    '') ;;
    --verbose) installer_verbose=1 ;;
    --help|-h) printf 'Usage: ./scripts/install.sh [--verbose]\n'; exit 0 ;;
    *) printf 'Usage: ./scripts/install.sh [--verbose]\n' >&2; exit 2 ;;
esac
if (( $# > 1 )); then
    printf 'Usage: ./scripts/install.sh [--verbose]\n' >&2
    exit 2
fi

# Keep diagnostics visible even when an error occurs inside a captured function.
exec 3>&2
# shellcheck source=scripts/install_ui.sh
source "$repo_root/scripts/install_ui.sh"
installer_ui
installer_log=$(mktemp)
installer_uv_script=''
installer_path_updated=0
installer_spinner_pid=''
installer_stage=$installer_title
trap installer_cleanup EXIT
trap 'installer_fail "$?"' ERR
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$(id -u)" == "0" ]]; then
    echo "Run this installer as your regular user, without sudo. System installation steps use sudo when needed." >&2
    exit 1
fi
# shellcheck source=scripts/docker_dependencies.sh
source "$repo_root/scripts/docker_dependencies.sh"
# shellcheck source=scripts/uv_dependencies.sh
source "$repo_root/scripts/uv_dependencies.sh"
docker_login_required=0
# Keep Docker setup in the foreground so sudo can ask for a password normally.
installer_step "$installer_docker" 0 ensure_docker
if ! command -v uv >/dev/null 2>&1; then
    installer_step "$installer_runtime" 1 ensure_uv
fi
installer_step "$installer_brig" 1 install_brig "$repo_root"
printf '\n  %s\n' "$installer_ready" >&3
if [[ "$docker_login_required" == 1 ]]; then
    printf '  %s\n' "$installer_login" >&3
fi
if [[ "$installer_path_updated" == 0 ]] && command -v brig >/dev/null 2>&1; then
    printf '  %s\n' "$installer_next" >&3
else
    printf '  %s\n' "$installer_path" >&3
fi
