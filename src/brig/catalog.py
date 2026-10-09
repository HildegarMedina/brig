"""A deliberately static demonstration catalog, not a live version registry."""

from dataclasses import dataclass

from brig.errors import BrigError


@dataclass(frozen=True)
class Tool:
    versions: tuple[str, ...]
    runtime: str


RUNTIMES = {
    "python": ("3.12.8", "3.11.11"),
    "php": ("8.3.15", "8.2.27"),
    "node": ("22.13.1", "20.18.2"),
}
TOOLS = {
    "pip": Tool(("24.3.1",), "python"),
    "uv": Tool(("0.5.24",), "python"),
    "composer": Tool(("2.8.5",), "php"),
    "npm": Tool(("10.9.2",), "node"),
}
SERVICES = {
    "postgresql": ("17.2", "16.6"),
    "redis": ("7.4.2", "7.2.7"),
}


@dataclass(frozen=True)
class Agent:
    name: str
    available: bool


AGENTS = {
    "claude": Agent("Claude Code", True),
    "codex": Agent("Codex", False),
    "opencode": Agent("OpenCode", False),
}


def validate_selection(
    runtimes: dict[str, str],
    tools: dict[str, str],
    services: dict[str, str],
    agent: str,
) -> None:
    if not runtimes:
        raise BrigError("Select at least one runtime.")
    catalogs = (
        ("runtime", runtimes, RUNTIMES),
        ("tool", tools, {name: tool.versions for name, tool in TOOLS.items()}),
        ("service", services, SERVICES),
    )
    for kind, selections, catalog in catalogs:
        for name, version in selections.items():
            if name not in catalog or version not in catalog[name]:
                raise BrigError(f"Unsupported demo {kind}: {name} {version}.")
    for name in tools:
        required = TOOLS[name].runtime
        if required not in runtimes:
            raise BrigError(f"{name} requires the {required} runtime.")
    if agent not in AGENTS or not AGENTS[agent].available:
        raise BrigError("Only Claude Code is available in this demo.")
