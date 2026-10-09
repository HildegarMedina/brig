"""Application records, independent of terminal and storage concerns."""

from dataclasses import dataclass, field


@dataclass
class ProfileRevision:
    number: int
    runtimes: dict[str, str]
    tools: dict[str, str]
    services: dict[str, str]
    agent: str = "claude"


@dataclass
class Profile:
    name: str
    revisions: list[ProfileRevision]

    @property
    def latest(self) -> ProfileRevision:
        return self.revisions[-1]


@dataclass
class Project:
    id: str
    name: str
    path: str | None
    profile: str
    configuration: ProfileRevision
    running: bool = False


@dataclass
class State:
    profiles: list[Profile] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
