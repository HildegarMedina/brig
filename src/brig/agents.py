"""Agent integrations: installation, execution and persistent configuration."""

from dataclasses import dataclass

from brig.errors import BrigError


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

    @property
    def available(self) -> bool:
        return bool(self.stage and self.image)


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
            "COPY --from=claude_binary /usr/local/bin/claude /usr/local/bin/claude",
            "ENV DISABLE_AUTOUPDATER=1",
            "",
        ),
        packages=("libstdc++6",),
        config_directory="/home/brig/.config/claude",
        config_environment="CLAUDE_CONFIG_DIR",
        history_directory="projects",
    ),
    "codex": AgentIntegration("Codex", ("codex",)),
    "opencode": AgentIntegration("OpenCode", ("opencode",)),
}


def validate_agent(agent: str) -> None:
    if not isinstance(agent, str) or agent not in AGENTS:
        raise BrigError(f"Unknown agent: {agent}.")
    if not AGENTS[agent].available:
        raise BrigError(f"{AGENTS[agent].name} is a future integration.")


def validate_agents(agents: list[str], default: str) -> None:
    if not isinstance(agents, list) or not agents:
        raise BrigError("Select at least one agent.")
    for agent in agents:
        validate_agent(agent)
    if len(set(agents)) != len(agents):
        raise BrigError("Select each agent only once.")
    if default not in agents:
        raise BrigError("The default agent must be one of the selected agents.")
