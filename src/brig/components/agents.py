"""Agent integrations: installation, execution and persistent configuration."""

import shlex
from dataclasses import dataclass

from brig.errors import BrigError
from brig.i18n import tr


@dataclass(frozen=True)
class AgentIntegration:
    name: str
    command: tuple[str, ...]
    stage: tuple[str, ...] = ()
    image: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    config_directory: str | None = None
    config_environment: str | None = None
    history_directory: str | None = None
    extra_history_directories: tuple[str, ...] = ()

    @property
    def history_directories(self) -> tuple[str, ...]:
        return (
            (self.history_directory,) if self.history_directory else ()
        ) + self.extra_history_directories

    @property
    def available(self) -> bool:
        return bool(self.stage and self.image)


def command_wrapper(name: str, command: tuple[str, ...], *, prepare=()) -> str:
    lines = (
        "#!/bin/sh",
        "set -eu",
        "if [ -f /opt/brig-auth/environment.sh ]; then . /opt/brig-auth/environment.sh; fi",
        *prepare,
        "exec " + shlex.join(command) + ' "$@"',
    )
    return (
        "RUN printf '%s\\n' "
        + " ".join(shlex.quote(line) for line in lines)
        + f" > /usr/local/bin/{name} && chmod 755 /usr/local/bin/{name}"
    )


AGENTS = {
    "claude": AgentIntegration(
        name="Claude Code",
        command=("claude",),
        stage=(
            "FROM debian:bookworm-slim AS claude_binary",
            "RUN set -eux; \\",
            "    apt-get update; \\",
            "    apt-get install -y --no-install-recommends ca-certificates curl libstdc++6; \\",
            "    curl -fsSL https://claude.ai/install.sh -o /tmp/install-claude.sh; \\",
            "    bash /tmp/install-claude.sh stable; \\",
            "    test -x /root/.local/bin/claude; \\",
            "    cp -L /root/.local/bin/claude /usr/local/bin/claude; \\",
            "    claude --version",
            "",
        ),
        image=(
            "# Keep the agent executable outside persistent configuration volumes.",
            "COPY --from=claude_binary /usr/local/bin/claude /opt/brig-claude/claude",
            command_wrapper(
                "claude",
                (
                    "/opt/brig-claude/claude",
                    "--dangerously-skip-permissions",
                    "--settings",
                    '{"skipDangerousModePermissionPrompt":true}',
                ),
            ),
            "ENV DISABLE_AUTOUPDATER=1",
            "",
        ),
        packages=("libstdc++6",),
        config_directory="/home/brig/.config/claude",
        config_environment="CLAUDE_CONFIG_DIR",
        history_directory="projects",
    ),
    "codex": AgentIntegration(
        name="Codex",
        command=("codex",),
        stage=(
            "FROM debian:bookworm-slim AS codex_binary",
            "RUN set -eux; \\",
            "    apt-get update; \\",
            "    apt-get install -y --no-install-recommends ca-certificates curl; \\",
            "    curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/install-codex.sh; \\",
            "    CODEX_HOME=/opt/brig-codex CODEX_INSTALL_DIR=/usr/local/bin CODEX_NON_INTERACTIVE=1 sh /tmp/install-codex.sh; \\",
            "    test -x /opt/brig-codex/packages/standalone/current/bin/codex; \\",
            "    /usr/local/bin/codex --version",
            "",
        ),
        image=(
            "COPY --from=codex_binary /opt/brig-codex/ /opt/brig-codex/",
            command_wrapper(
                "codex",
                (
                    "/opt/brig-codex/packages/standalone/current/bin/codex",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--enable",
                    "respect_system_proxy",
                    "-c",
                    'cli_auth_credentials_store="file"',
                    "-c",
                    'sqlite_home="/home/brig/.local/state/codex"',
                    "-c",
                    'log_dir="/home/brig/.local/state/codex/logs"',
                    "-c",
                    "check_for_update_on_startup=false",
                ),
                prepare=("mkdir -p /home/brig/.local/state/codex",),
            ),
            "",
        ),
        config_directory="/home/brig/.config/codex",
        config_environment="CODEX_HOME",
        history_directory="sessions",
        extra_history_directories=("archived_sessions",),
    ),
    "opencode": AgentIntegration(
        name="OpenCode",
        command=("opencode",),
        stage=(
            "FROM debian:bookworm-slim AS opencode_binary",
            "RUN set -eux; \\",
            "    apt-get update; \\",
            "    apt-get install -y --no-install-recommends ca-certificates curl unzip libstdc++6; \\",
            "    curl -fsSL https://opencode.ai/install -o /tmp/install-opencode.sh; \\",
            "    bash /tmp/install-opencode.sh --no-modify-path; \\",
            "    /root/.opencode/bin/opencode --version",
            "",
        ),
        image=(
            "COPY --from=opencode_binary /root/.opencode/bin/opencode /opt/brig-opencode/opencode",
            "ENV OPENCODE_CONFIG_DIR=/home/brig/.local/share/opencode/config",
            "ENV OPENCODE_DB=/home/brig/.local/state/opencode/brig.db",
            "ENV OPENCODE_DISABLE_AUTOUPDATE=1",
            command_wrapper(
                "opencode",
                ("/opt/brig-opencode/opencode", "--auto"),
                prepare=(
                    "mkdir -p /home/brig/.local/state/opencode",
                    """export OPENCODE_PERMISSION='{"*":"allow"}'""",
                ),
            ),
            "",
        ),
        packages=("libstdc++6",),
        config_directory="/home/brig/.local/share/opencode",
        history_directory="project",
        extra_history_directories=("storage",),
    ),
}


def validate_agent(agent: str) -> None:
    if not isinstance(agent, str) or agent not in AGENTS:
        raise BrigError(tr("Unknown agent: {value0}.").format(value0=agent))
    if not AGENTS[agent].available:
        raise BrigError(
            tr("{value0} is a future integration.").format(value0=AGENTS[agent].name)
        )


def validate_agents(agents: list[str], default: str) -> None:
    if not isinstance(agents, list) or not agents:
        raise BrigError(tr("Select at least one agent."))
    for agent in agents:
        validate_agent(agent)
    if len(set(agents)) != len(agents):
        raise BrigError(tr("Select each agent only once."))
    if default not in agents:
        raise BrigError(tr("The default agent must be one of the selected agents."))


def validate_project_agent(configuration, agent: str) -> None:
    validate_agent(agent)
    if agent not in configuration.selected_agents:
        raise BrigError(
            tr("Agent '{value0}' is not selected in this project's profile.").format(
                value0=agent
            )
        )
    if agent != configuration.agent:
        raise BrigError(
            tr(
                "This project uses '{active}'. Only its default agent is installed and authorized."
            ).format(active=configuration.agent)
        )
