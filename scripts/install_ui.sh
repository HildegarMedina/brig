#!/usr/bin/env bash
# Presentation only: keep setup decisions in install.sh and docker_dependencies.sh.
# These labels are also read by install.sh.
# shellcheck disable=SC2034

installer_ui() {
    local candidate language=en
    for candidate in "${BRIG_LANG:-}" "${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}"; do
        case "${candidate,,}" in
            es|es[_-]*|es.*) language=es; break ;;
            pt|pt[_-]*|pt.*) language=pt; break ;;
            en|en[_-]*|en.*) break ;;
        esac
    done
    case "$language" in
        es)
            installer_title=Instalador
            installer_docker='Preparando Docker'
            installer_runtime='Preparando instalador'
            installer_brig='Instalando Brig'
            installer_ready='Brig instalado.'
            installer_next='Ejecuta: brig'
            installer_path='Abre otra terminal y ejecuta: brig'
            installer_login='Vuelve a iniciar sesión antes de usar los entornos.'
            installer_failed='No se pudo completar'
            ;;
        pt)
            installer_title=Instalador
            installer_docker='Preparando Docker'
            installer_runtime='Preparando instalador'
            installer_brig='Instalando Brig'
            installer_ready='Brig instalado.'
            installer_next='Execute: brig'
            installer_path='Abra outro terminal e execute: brig'
            installer_login='Entre novamente na sessão antes de usar os ambientes.'
            installer_failed='Não foi possível concluir'
            ;;
        *)
            installer_title=Installer
            installer_docker='Preparing Docker'
            installer_runtime='Preparing installer'
            installer_brig='Installing Brig'
            installer_ready='Brig installed.'
            installer_next='Run: brig'
            installer_path='Open a new terminal and run: brig'
            installer_login='Log out and back in before using environments.'
            installer_failed='Could not complete'
            ;;
    esac
    installer_color='' installer_reset=''
    installer_animated=0
    installer_columns=${COLUMNS:-80}
    if [[ -t 2 && "${TERM:-dumb}" != dumb ]]; then
        if command -v tput >/dev/null 2>&1; then
            installer_columns=$(tput cols 2>/dev/null || printf '80')
        fi
        if [[ ! ${NO_COLOR+x} && ! ${CI:-} ]]; then
            installer_color=$'\033[36m' installer_reset=$'\033[0m'
        fi
        if [[ ! ${CI:-} && ! ${BRIG_NO_ANIMATION:-} && "${installer_verbose:-0}" == 0 ]]; then
            installer_animated=1
        fi
    fi
    [[ "$installer_columns" =~ ^[0-9]+$ ]] || installer_columns=80
    if (( installer_columns < 40 )); then
        installer_animated=0
    fi
    printf '\n%s' "$installer_color" >&3
    if [[ -t 2 ]] && (( installer_columns >= 32 )); then
        cat >&3 <<'SHIP'
       |    |
      /|\  /|\
     /_|_\/_|_\
     \________/
  ~   ~  ~   ~   ~  ~
SHIP
    else
        printf '  ~ |\|\__/ ~\n' >&3
    fi
    printf '  BRIG / %s%s\n\n' "$installer_title" "$installer_reset" >&3
}

installer_stop_animation() {
    if [[ -n "${installer_spinner_pid:-}" ]]; then
        kill "$installer_spinner_pid" 2>/dev/null || true
        wait "$installer_spinner_pid" 2>/dev/null || true
        installer_spinner_pid=''
        printf '\r\033[2K' >&3
    fi
}

installer_cleanup() {
    installer_stop_animation
    rm -f -- "${installer_log:-}"
    rm -f -- "${installer_uv_script:-}"
}

installer_fail() {
    local code=$1
    trap - ERR
    installer_stop_animation
    printf '\n  [!] %s: %s\n' "$installer_failed" "$installer_stage" >&3
    if [[ -s "$installer_log" ]]; then
        tail -n 30 "$installer_log" >&3
    fi
    exit "$code"
}

installer_step() {
    installer_stage=$1
    local animate=$2
    shift 2
    : > "$installer_log"
    if [[ "$animate" == 1 && "$installer_animated" == 1 ]]; then
        (
            trap - ERR EXIT INT TERM
            local wave=0
            while :; do
                if (( wave % 2 == 0 )); then
                    printf '\r  %s...  ~ |\|\__/ ~ ' "$installer_stage" >&3
                else
                    printf '\r  %s...   ~|\|\__/  ~' "$installer_stage" >&3
                fi
                wave=$((wave + 1))
                sleep 0.2
            done
        ) &
        installer_spinner_pid=$!
    else
        printf '  %s...\n' "$installer_stage" >&3
    fi
    if [[ "$installer_verbose" == 1 ]]; then
        "$@"
    else
        "$@" > "$installer_log" 2>&1
    fi
    if [[ -n "${installer_spinner_pid:-}" ]]; then
        installer_stop_animation
        printf '  %s... [ok]\n' "$installer_stage" >&3
    fi
}
