"""Environment description and execution contract."""

from dataclasses import dataclass, field
from typing import Protocol

from brig.models import Project


@dataclass(frozen=True)
class Environment:
    development: str
    services: dict[str, str]
    network: str
    volumes: tuple[str, ...]
    agents: dict[str, str] = field(default_factory=dict)


class EnvironmentEngine(Protocol):
    simulated: bool

    def is_running(self, project: Project) -> bool: ...

    def has_running_resources(self, project: Project) -> bool: ...

    def validate_shell(self, command=None) -> None: ...
    def describe(self, project: Project) -> Environment: ...

    def start(self, project: Project) -> str: ...

    def stop(self, project: Project) -> str: ...

    def run_agent(self, project: Project, agent: str, command=None) -> str: ...

    def shell(self, project: Project, command=None) -> str: ...
