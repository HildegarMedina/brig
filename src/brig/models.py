"""Application records, independent of terminal and storage concerns."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProfileParent:
    profile: str
    version: int


@dataclass
class ProfileVersion:
    number: int
    runtimes: dict[str, str]
    tools: dict[str, str]
    services: dict[str, str]
    agent: str = "claude"
    agents: list[str] | None = None
    extends: ProfileParent | None = None

    @property
    def selected_agents(self) -> list[str]:
        # Legacy versions keep their YAML unchanged and select their one agent.
        return [self.agent] if self.agents is None else list(self.agents)


@dataclass
class Profile:
    name: str
    versions: list[ProfileVersion]

    @property
    def latest(self) -> ProfileVersion:
        return self.versions[-1]


@dataclass
class Project:
    id: str
    name: str
    path: str | None
    profile: str
    configuration: ProfileVersion
    running: bool = False


@dataclass
class State:
    profiles: list[Profile] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
