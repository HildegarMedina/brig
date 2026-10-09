"""Use cases shared by command-line and interactive interfaces."""

from copy import deepcopy
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from brig.catalog import VersionCatalog, validate_selection
from brig.versions import LiveVersionCatalog
from brig.engine import EnvironmentEngine
from brig.errors import BrigError
from brig.models import Profile, ProfileRevision, Project, State
from brig.storage import StateStore


class Application:
    def __init__(
        self,
        store: StateStore,
        engine: EnvironmentEngine,
        catalog_factory: Callable[[], VersionCatalog] = LiveVersionCatalog,
    ):
        self.store = store
        self.engine = engine
        self.catalog_factory = catalog_factory
        loaded = store.load()
        self.state = loaded if loaded is not None else State()
        if loaded is None:
            store.save(self.state)

    def profile(self, name: str) -> Profile:
        for profile in self.state.profiles:
            if profile.name.casefold() == name.casefold():
                return profile
        raise BrigError(f"Unknown profile: {name}.")

    def project(self, name: str) -> Project:
        for project in self.state.projects:
            if project.name.casefold() == name.casefold():
                return project
        raise BrigError(f"Unknown project: {name}.")

    def resolve_project(self, name: str | None, directory: Path) -> Project:
        if name:
            return self.project(name)
        current = directory.resolve()
        matches = [
            p
            for p in self.state.projects
            if p.path is not None and current.is_relative_to(Path(p.path))
        ]
        if matches:
            return max(matches, key=lambda p: len(Path(p.path).parts))
        raise BrigError(
            "No project found for this folder. Use --project <name> or 'brig project init'."
        )

    def validate_profile_name(self, name: str, *, editing: bool = False) -> str:
        name = self._validate_name(name)
        if not editing and any(
            p.name.casefold() == name.casefold() for p in self.state.profiles
        ):
            raise BrigError(f"Profile '{name}' already exists. Choose another name.")
        return name

    def save_profile(
        self,
        name: str,
        runtimes: dict[str, str],
        tools: dict[str, str],
        services: dict[str, str],
        agent: str = "claude",
        *,
        editing: bool = False,
        catalog: VersionCatalog | None = None,
    ) -> Profile:
        name = self.validate_profile_name(name, editing=editing)
        validate_selection(
            runtimes,
            tools,
            services,
            agent,
            versions=catalog if catalog is not None else self.catalog_factory(),
        )
        candidate = deepcopy(self.state)
        if editing:
            original = self.profile(name)
            profile = next(p for p in candidate.profiles if p.name == original.name)
        else:
            profile = Profile(name, [])
            candidate.profiles.append(profile)
        profile.revisions.append(
            ProfileRevision(
                len(profile.revisions) + 1,
                dict(runtimes),
                dict(tools),
                dict(services),
                agent,
            )
        )
        self._commit(candidate)
        return profile

    def profile_for_deletion(self, name: str) -> Profile:
        profile = self.profile(name)
        projects = [
            project.name
            for project in self.state.projects
            if project.profile == profile.name
        ]
        if projects:
            raise BrigError(
                f"Cannot delete profile '{profile.name}'. Used by projects: {', '.join(projects)}."
            )
        return profile

    def delete_profile(self, name: str) -> str:
        profile = self.profile_for_deletion(name)
        candidate = deepcopy(self.state)
        candidate.profiles = [
            item for item in candidate.profiles if item.name != profile.name
        ]
        self.store.delete_profile(candidate, profile)
        self.state = candidate
        return f"Deleted profile '{profile.name}' and all its revisions."

    def create_project(self, name: str, path: Path, profile_name: str) -> Project:
        name = self._validate_name(name)
        if any(p.name.casefold() == name.casefold() for p in self.state.projects):
            raise BrigError(f"Project '{name}' already exists.")
        directory = path.expanduser().resolve()
        if not directory.is_dir():
            raise BrigError(f"Project folder does not exist: {directory}")
        if any(p.path == str(directory) for p in self.state.projects):
            raise BrigError("This folder is already registered as a project.")
        profile = self.profile(profile_name)
        project = Project(
            uuid4().hex, name, str(directory), profile.name, deepcopy(profile.latest)
        )
        candidate = deepcopy(self.state)
        candidate.projects.append(project)
        self._commit(candidate)
        return project

    def update_project(self, name: str) -> str:
        project = self.project(name)
        latest = self.profile(project.profile).latest
        if latest.number == project.configuration.number:
            return f"{project.name} already uses the latest profile revision."
        if project.running:
            raise BrigError("Stop the project before applying a profile update.")
        candidate = deepcopy(self.state)
        target = next(p for p in candidate.projects if p.id == project.id)
        target.configuration = deepcopy(latest)
        self._commit(candidate)
        return (
            f"Updated {project.name} to profile revision {latest.number} (simulated)."
        )

    def start(self, name: str) -> str:
        return self._set_running(name, True)

    def stop(self, name: str) -> str:
        return self._set_running(name, False)

    def run_agent(self, name: str, agent: str) -> str:
        return self.engine.run_agent(self.project(name), agent)

    def shell(self, name: str) -> str:
        return self.engine.shell(self.project(name))

    def _set_running(self, name: str, running: bool) -> str:
        project = self.project(name)
        message = self.engine.start(project) if running else self.engine.stop(project)
        if project.running != running:
            candidate = deepcopy(self.state)
            next(p for p in candidate.projects if p.id == project.id).running = running
            self._commit(candidate)
        return message

    def _commit(self, state: State) -> None:
        self.store.save(state)
        self.state = state

    @staticmethod
    def _validate_name(name: str) -> str:
        name = name.strip()
        if (
            not name
            or len(name) > 64
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
        ):
            raise BrigError(
                "Name must contain 1–64 characters without control characters."
            )
        return name
