"""Execution protocol and a simulation used by isolated application tests."""

from dataclasses import dataclass
from typing import Protocol

from brig.agents import AGENTS, validate_agent
from brig.errors import BrigError
from brig.models import Project


@dataclass(frozen=True)
class Environment:
    development: str
    services: dict[str, str]
    network: str
    volumes: tuple[str, ...]


class EnvironmentEngine(Protocol):
    simulated: bool

    def is_running(self, project: Project) -> bool: ...

    def has_running_resources(self, project: Project) -> bool: ...

    def validate_shell(self, command=None) -> None: ...
    def describe(self, project: Project) -> Environment: ...

    def start(self, project: Project) -> str: ...

    def stop(self, project: Project) -> str: ...

    def run_agent(self, project: Project, agent: str) -> str: ...

    def shell(self, project: Project, command=None) -> str: ...


class DemoEngine:
    simulated = True

    def is_running(self, project: Project) -> bool:
        return project.running

    def has_running_resources(self, project: Project) -> bool:
        return self.is_running(project)

    def validate_shell(self, command=None) -> None:
        pass

    def describe(self, project: Project) -> Environment:
        prefix = f"brig-{project.id}"
        services = {name: f"{prefix}-{name}" for name in project.configuration.services}
        return Environment(
            development=f"{prefix}-dev",
            services=services,
            network=f"{prefix}-network",
            volumes=(f"{prefix}-agent-data",)
            + tuple(f"{name}-data" for name in services.values()),
        )

    def start(self, project: Project) -> str:
        if project.running:
            return f"{project.name} is already running (simulated)."
        return f"Started {project.name} (simulated). No containers were created."

    def stop(self, project: Project) -> str:
        if not project.running:
            return f"{project.name} is already stopped (simulated)."
        return f"Stopped {project.name} (simulated). Project data is preserved."

    def run_agent(self, project: Project, agent: str) -> str:
        validate_agent(agent)
        self._require_running(project)
        return (
            f"Would launch {AGENTS[agent].name} inside {self.describe(project).development}.\n"
            "Simulation only: no agent was launched and no credentials are needed."
        )

    def shell(self, project: Project, command=None) -> str:
        self._require_running(project)
        return (
            f"Would open a shell inside {self.describe(project).development} at /workspace.\n"
            "Simulation only: no shell was opened."
        )

    @staticmethod
    def _require_running(project: Project) -> None:
        if not project.running:
            raise BrigError("Project is stopped. Start it with 'brig up' first.")
