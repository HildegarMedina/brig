"""Extensible component definitions; release numbers belong to live providers."""

import re
from dataclasses import dataclass
from typing import Protocol

from brig.components.agents import validate_agent
from brig.errors import BrigError
from brig.i18n import tr


@dataclass(frozen=True)
class Component:
    label: str
    category: str
    provider: str
    package: str
    runtime: str | None = None
    version_parts: int = 3
    version_prefix: str = ""
    # Only offer releases that also publish this image variant, e.g. Debian.
    tag_suffix: str = ""
    # Image the build pulls; releases are offered only once it is published.
    # Java build tools also format it with the selected Java major.
    image: str = ""


RUNTIMES = {
    # Every runtime uses the same Debian release, including in mixed profiles.
    "php": Component(
        "PHP",
        "Runtimes",
        "docker",
        "php",
        image="php:{version}-cli-bookworm",
    ),
    "python": Component(
        "Python",
        "Runtimes",
        "docker",
        "python",
        image="python:{version}-bookworm",
    ),
    "node": Component(
        "Node.js",
        "Runtimes",
        "docker",
        "node",
        image="node:{version}-bookworm",
    ),
    "go": Component(
        "Go",
        "Runtimes",
        "docker",
        "golang",
        tag_suffix="-bookworm",
        image="golang:{version}-bookworm",
    ),
    "rust": Component(
        "Rust",
        "Runtimes",
        "docker",
        "rust",
        tag_suffix="-bookworm",
        image="rust:{version}-bookworm",
    ),
    # Temurin images are Ubuntu-based; only the self-contained JDK is copied.
    "java": Component(
        "Java (Eclipse Temurin)",
        "Runtimes",
        "docker",
        "eclipse-temurin",
        version_parts=1,
        tag_suffix="-jdk",
        image="eclipse-temurin:{version}-jdk",
    ),
}
TOOLS = {
    "composer": Component(
        "Composer",
        "PHP package managers",
        "composer",
        "composer",
        "php",
        image="composer:{version}",
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
    # Build tools are pure Java distributions; each image tag pairs one with a JDK.
    "maven": Component(
        "Maven",
        "Java build tools",
        "docker",
        "maven",
        "java",
        image="maven:{version}-eclipse-temurin-{java}",
    ),
    "gradle": Component(
        "Gradle",
        "Java build tools",
        "docker",
        "gradle",
        "java",
        image="gradle:{version}-jdk{java}",
    ),
    "playwright": Component(
        "Playwright (Chromium)", "Browser automation", "npm", "playwright", "node"
    ),
}
SERVICES = {
    "postgresql": Component(
        "PostgreSQL",
        "Relational databases",
        "docker",
        "postgres",
        version_parts=2,
        image="postgres:{version}",
    ),
    "mysql": Component(
        "MySQL", "Relational databases", "docker", "mysql", image="mysql:{version}"
    ),
    "mariadb": Component(
        "MariaDB",
        "Relational databases",
        "docker",
        "mariadb",
        image="mariadb:{version}",
    ),
    "mongodb": Component(
        "MongoDB", "Document databases", "docker", "mongo", image="mongo:{version}"
    ),
    "redis": Component(
        "Redis",
        "Caches / key-value stores",
        "docker",
        "redis",
        image="redis:{version}",
    ),
    # The management variant adds the HTTP API and rabbitmqadmin for inspection.
    "rabbitmq": Component(
        "RabbitMQ",
        "Message brokers",
        "docker",
        "rabbitmq",
        tag_suffix="-management",
        image="rabbitmq:{version}-management",
    ),
    # Apache publishes Kafka on Docker Hub, not as a Docker Official Image.
    "kafka": Component(
        "Apache Kafka",
        "Message brokers",
        "dockerhub",
        "apache/kafka",
        image="apache/kafka:{version}",
    ),
}
COMPONENTS = {**RUNTIMES, **TOOLS, **SERVICES}

# Profile YAML groups services by category; other categories are databases.
SERVICE_SECTIONS = {
    "Caches / key-value stores": "caches",
    "Message brokers": "message_brokers",
}


def service_section(name: str) -> str:
    return SERVICE_SECTIONS.get(SERVICES[name].category, "databases")


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
    inherited: set[str] | frozenset[str] = frozenset(),
) -> None:
    """Validate stored shape offline; verify new selections against a live snapshot."""
    if not runtimes:
        raise BrigError(tr("Select at least one runtime."))
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
                raise BrigError(
                    tr("Unsupported {value0}: {value1} {value2}.").format(
                        value0=tr(kind), value1=name, value2=version
                    )
                )
    for name in tools:
        required = TOOLS[name].runtime
        if required not in runtimes:
            raise BrigError(
                tr("{value0} requires the {value1} runtime.").format(
                    value0=name, value1=required
                )
            )
    validate_agent(agent)
    if versions is not None:
        for selections in (runtimes, tools, services):
            for name, version in selections.items():
                if name in inherited:
                    continue
                if version not in versions.versions(name):
                    raise BrigError(
                        tr(
                            "{value0} {value1} is not available from its version source."
                        ).format(value0=name, value1=version)
                    )
        for name, version in tools.items():
            if name in inherited:
                continue
            issue = versions.compatibility_issue(name, version, runtimes)
            if issue:
                raise BrigError(issue)
