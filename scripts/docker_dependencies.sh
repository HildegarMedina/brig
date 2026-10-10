#!/usr/bin/env bash
# Shared host dependency setup; sourced by install.sh.

docker_cli_ready() {
    command -v docker >/dev/null 2>&1 && docker --version >/dev/null 2>&1
}

compose_ready() {
    local compose_version
    compose_version="$(docker compose version --short 2>/dev/null)" || return 1
    [[ "$compose_version" =~ ^v?([0-9]+)\. ]] && (( BASH_REMATCH[1] >= 2 ))
}

as_root() {
    if ! command -v sudo >/dev/null 2>&1; then
        echo "Installing Docker requires sudo. Ask your administrator to install Docker Engine and Compose." >&2
        return 1
    fi
    sudo "$@"
}

load_docker_platform() {
    if [[ ! -r /etc/os-release ]]; then
        echo "Cannot detect Linux distribution. Install Docker Engine and Compose manually." >&2
        return 1
    fi
    # System-owned release metadata, as used by Docker's repository instructions.
    source /etc/os-release
    docker_distribution="${ID:-}"
    docker_codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
    case "$docker_distribution:$docker_codename" in
        ubuntu:jammy|ubuntu:noble|ubuntu:resolute|debian:bookworm|debian:trixie) ;;
        *)
            echo "Automatic Docker installation is unsupported on ${PRETTY_NAME:-this system}. See https://docs.docker.com/engine/install/" >&2
            return 1
            ;;
    esac
}

install_docker_packages() {
    local packages=(docker-compose-plugin)
    if ! docker_cli_ready || [[ "${1:-}" == engine ]]; then
        packages+=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin)
    fi
    load_docker_platform
    echo "Installing missing Docker dependencies from Docker's official repository..."
    as_root apt-get update
    as_root apt-get install -y --no-remove --no-upgrade ca-certificates curl
    # Preserve repositories already configured by the user or administrator.
    if [[ ! -f /etc/apt/sources.list.d/docker.sources && ! -f /etc/apt/sources.list.d/docker.list ]]; then
        as_root install -m 0755 -d /etc/apt/keyrings
        as_root curl -fsSL "https://download.docker.com/linux/$docker_distribution/gpg" -o /etc/apt/keyrings/docker.asc
        as_root chmod a+r /etc/apt/keyrings/docker.asc
        as_root tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/$docker_distribution
Suites: $docker_codename
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    fi
    as_root apt-get update
    # Fail on package conflicts rather than removing/replacing an existing stack.
    as_root apt-get install -y --no-remove --no-upgrade "${packages[@]}"
}

ensure_docker_access() {
    if docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
        echo "Docker daemon is accessible."
        return
    fi
    local endpoint
    endpoint="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)}"
    if [[ "$endpoint" != "unix:///var/run/docker.sock" ]]; then
        echo "Cannot reach Docker at $endpoint. Start your configured daemon and check access; Brig keeps your Docker context." >&2
        return 1
    fi
    if ! as_root docker --host "$endpoint" version --format '{{.Server.Version}}' >/dev/null 2>&1; then
        if ! command -v systemctl >/dev/null 2>&1; then
            echo "Start the Docker daemon manually, then run this installer again." >&2
            return 1
        fi
        if ! systemctl cat docker.service >/dev/null 2>&1; then
            # A Docker CLI alone does not provide a local daemon.
            install_docker_packages engine
        fi
        as_root systemctl enable --now docker
        as_root docker --host "$endpoint" version --format '{{.Server.Version}}' >/dev/null
    fi
    if [[ " $(id -nG) " != *" docker "* ]]; then
        as_root groupadd -f docker
        as_root usermod -aG docker "$(id -un)"
        echo "Docker access configured for $(id -un). Log out and back in before running Brig environments."
        return
    fi
    echo "Docker is running but your session cannot access it. Check socket permissions or log out and back in." >&2
    return 1
}

ensure_docker() {
    if [[ "$(uname -s)" != "Linux" ]]; then
        echo "Brig's installer requires Linux." >&2
        return 1
    fi
    if ! docker_cli_ready || ! compose_ready; then
        install_docker_packages
    fi
    if ! docker_cli_ready || ! compose_ready; then
        echo "Docker Engine CLI and Compose v2 or newer must be available after installation." >&2
        return 1
    fi
    ensure_docker_access
}
