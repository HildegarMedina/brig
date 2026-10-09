"""Small test doubles shared across application and interface tests."""

from copy import deepcopy
from uuid import uuid4

from brig.models import Profile, ProfileRevision, Project, State

from brig.errors import BrigError


class FakeVersionCatalog:
    """Deterministic release source; production has no baked-in versions."""

    def __init__(self, versions=None):
        self.available = (
            versions
            if versions is not None
            else {
                "python": ("3.12.8", "3.11.11"),
                "php": ("8.3.15", "8.2.27"),
                "node": ("22.13.1", "20.18.2"),
                "pip": ("24.3.1",),
                "uv": ("0.5.24",),
                "composer": ("2.8.5",),
                "npm": ("10.9.2",),
                "pnpm": ("9.15.0",),
                "yarn": ("1.22.22",),
                "playwright": ("1.50.1",),
                "postgresql": ("17.2", "16.6"),
                "redis": ("7.4.2", "7.2.7"),
                "mysql": ("8.4.3",),
                "mariadb": ("11.4.4",),
                "mongodb": ("8.0.4",),
            }
        )
        self.calls = []

    def versions(self, name):
        self.calls.append(name)
        value = self.available.get(name, ())
        if isinstance(value, Exception):
            raise value
        return value

    def label(self, name, version):
        return version

    def preferred_version(self, name, versions):
        return versions[0]

    def compatible_versions(self, name, runtimes):
        return self.versions(name)

    def compatibility_issue(self, name, version, runtimes):
        return None


class MemoryStore:
    def __init__(self, state=None):
        self.state = deepcopy(state)
        self.fail = False

    def load(self):
        return deepcopy(self.state)

    def save(self, state):
        if self.fail:
            raise BrigError("Disk is full")
        self.state = deepcopy(state)

    def delete_profile(self, state, profile):
        self.save(state)


def demo_state() -> State:
    web = ProfileRevision(
        1, {"php": "8.3.15"}, {"composer": "2.8.5"}, {"postgresql": "17.2"}
    )
    python = ProfileRevision(1, {"python": "3.11.11"}, {"uv": "0.5.24"}, {})
    python_new = ProfileRevision(
        2, {"python": "3.12.8"}, {"uv": "0.5.24"}, {"redis": "7.4.2"}
    )
    return State(
        profiles=[
            Profile("web_dev", [web]),
            Profile("python_dev", [python, python_new]),
        ],
        projects=[
            Project(uuid4().hex, "website", None, "web_dev", deepcopy(web)),
            Project(uuid4().hex, "api", None, "python_dev", deepcopy(python_new), True),
        ],
    )
