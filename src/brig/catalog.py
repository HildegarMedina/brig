"""Extensible component definitions; release numbers belong to live providers."""

from dataclasses import dataclass
import re
from typing import Protocol

from brig.errors import BrigError
from brig.agents import AGENTS as AGENTS, validate_agent


@dataclass(frozen=True)
class Component:
    label: str
    category: str
    provider: str
    package: str
    runtime: str | None = None
    version_parts: int = 3
    version_prefix: str = ""


RUNTIMES = {
    "php": Component("PHP", "Runtimes", "docker", "php"),
    "python": Component("Python", "Runtimes", "docker", "python"),
    "node": Component("Node.js", "Runtimes", "docker", "node"),
}
TOOLS = {
    "composer": Component(
        "Composer", "PHP package managers", "composer", "composer", "php"
    ),
    "pip": Component("pip", "Python package managers", "pypi", "pip", "python"),
    "uv": Component("uv", "Python package managers", "pypi", "uv", "python"),
    "npm": Component("npm", "Node.js package managers", "npm", "npm", "node"),
    "pnpm": Component("pnpm", "Node.js package managers", "npm", "pnpm", "node"),
    "yarn": Component(
        "Yarn (Classic)",
        "Node.js package managers",
        "npm",
        "yarn",
        "node",
        version_prefix="1.",
    ),
    "playwright": Component(
        "Playwright (Chromium)", "Browser automation", "npm", "playwright", "node"
    ),
}
SERVICES = {
    "postgresql": Component(
        "PostgreSQL", "Relational databases", "docker", "postgres", version_parts=2
    ),
    "mysql": Component("MySQL", "Relational databases", "docker", "mysql"),
    "mariadb": Component("MariaDB", "Relational databases", "docker", "mariadb"),
    "mongodb": Component("MongoDB", "Document databases", "docker", "mongo"),
    "redis": Component("Redis", "Caches / key-value stores", "docker", "redis"),
}
COMPONENTS = {**RUNTIMES, **TOOLS, **SERVICES}


class VersionCatalog(Protocol):
    def versions(self, name: str) -> tuple[str, ...]: ...

    def label(self, name: str, version: str) -> str: ...

    def preferred_version(self, name: str, versions: list[str]) -> str: ...

    def compatible_versions(
        self, name: str, runtimes: dict[str, str]
    ) -> tuple[str, ...]: ...

    def compatibility_issue(
        self, name: str, version: str, runtimes: dict[str, str]
    ) -> str | None: ...


def validate_selection(
    runtimes: dict[str, str],
    tools: dict[str, str],
    services: dict[str, str],
    agent: str,
    *,
    versions: VersionCatalog | None = None,
) -> None:
    """Validate stored shape offline; verify new selections against a live snapshot."""
    if not runtimes:
        raise BrigError("Select at least one runtime.")
    for kind, selections, catalog in (
        ("runtime", runtimes, RUNTIMES),
        ("tool", tools, TOOLS),
        ("service", services, SERVICES),
    ):
        for name, version in selections.items():
            component = catalog.get(name)
            if (
                component is None
                or not isinstance(version, str)
                or not re.fullmatch(
                    rf"[0-9]+(?:\.[0-9]+){{{component.version_parts - 1}}}", version
                )
            ):
                raise BrigError(f"Unsupported {kind}: {name} {version}.")
    for name in tools:
        required = TOOLS[name].runtime
        if required not in runtimes:
            raise BrigError(f"{name} requires the {required} runtime.")
    validate_agent(agent)
    if versions is not None:
        for selections in (runtimes, tools, services):
            for name, version in selections.items():
                if version not in versions.versions(name):
                    raise BrigError(
                        f"{name} {version} is not available from its version source."
                    )
        for name, version in tools.items():
            issue = versions.compatibility_issue(name, version, runtimes)
            if issue:
                raise BrigError(issue)
