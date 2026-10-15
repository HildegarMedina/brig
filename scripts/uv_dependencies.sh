#!/usr/bin/env bash
# User-local Python tooling; sourced by the main installer.

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        return
    fi
    local uv_install_dir="${UV_INSTALL_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}"
    if [[ ! -x "$uv_install_dir/uv" ]]; then
        installer_uv_script=$(mktemp "${TMPDIR:-/tmp}/brig-uv.XXXXXX")
        if command -v curl >/dev/null 2>&1; then
            curl --fail --show-error --location --proto '=https' --proto-redir '=https' \
                --connect-timeout 15 --max-time 120 \
                https://astral.sh/uv/install.sh --output "$installer_uv_script"
        elif command -v wget >/dev/null 2>&1; then
            wget --quiet --timeout=30 --tries=3 \
                https://astral.sh/uv/install.sh --output-document="$installer_uv_script"
        else
            echo "Downloading uv requires curl or wget. Install either tool and run the installer again." >&2
            return 1
        fi
        # Let uv's tool setup configure the shell once, after Brig is installed.
        UV_INSTALL_DIR="$uv_install_dir" UV_NO_MODIFY_PATH=1 sh "$installer_uv_script"
        rm -f -- "$installer_uv_script"
        installer_uv_script=''
    fi
    if [[ ! -x "$uv_install_dir/uv" ]]; then
        echo "The uv installer did not create $uv_install_dir/uv. Check its installation output and try again." >&2
        return 1
    fi
    export PATH="$uv_install_dir:$PATH"
    # The caller's shell cannot inherit this installer's changed PATH.
    # shellcheck disable=SC2034 # Read by install.sh after this sourced function.
    installer_path_updated=1
}

install_brig() {
    uv tool install --python '>=3.12' --reinstall "$1"
    uv tool update-shell
}
