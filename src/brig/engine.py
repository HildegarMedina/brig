"""An execution boundary: the prototype implements only a simulation."""

from dataclasses import dataclass
from typing import Protocol

from brig.catalog import AGENTS
from brig.errors import BrigError
from brig.models import Project


@dataclass(frozen=True)
class Environment:
    development: str
    services: dict[str, str]
    network: str
    volumes: tuple[str, ...]


class EnvironmentEngine(Protocol):
    def describe(self, project: Project) -> Environment: ...

    def start(self, project: Project) -> str: ...

    def stop(self, project: Project) -> str: ...

    def run_agent(self, project: Project, agent: str) -> str: ...

    def shell(self, project: Project) -> str: ...


class DemoEngine:
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
        if agent not in AGENTS:
            raise BrigError(f"Unknown agent: {agent}.")
        if not AGENTS[agent].available:
            raise BrigError(f"{AGENTS[agent].name} is a future integration.")
        self._require_running(project)
        return (
            f"Would launch {AGENTS[agent].name} inside {self.describe(project).development}.\n"
            "Simulation only: no agent was launched and no credentials are needed."
        )

    def shell(self, project: Project) -> str:
        self._require_running(project)
        return (
            f"Would open a shell inside {self.describe(project).development} at /workspace.\n"
            "Simulation only: no shell was opened."
        )

    @staticmethod
    def _require_running(project: Project) -> None:
        if not project.running:
            raise BrigError("Project is stopped. Start it with 'brig up' first.")
