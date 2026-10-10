"""Use cases shared by command-line and interactive interfaces."""

import re
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from brig.components.agents import validate_agent, validate_agents
from brig.components.catalog import VersionCatalog, validate_selection
from brig.components.versions import LiveVersionCatalog
from brig.docker.dockerfile import render_dockerfile
from brig.engine import EnvironmentEngine
from brig.errors import BrigError
from brig.models import Profile, ProfileRevision, Project, State
from brig.persistence.export import write_dockerfile
from brig.persistence.store import StateStore


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
        if editing:
            # Existing records remain editable; this flow does not rename them.
            return self.profile(name.strip()).name
        name = name.strip()
        if not editing and any(
            p.name.casefold() == name.casefold() for p in self.state.profiles
        ):
            raise BrigError(f"Profile '{name}' already exists. Choose another name.")
        return self._validate_name(name)

    def validate_project_name(self, name: str) -> str:
        name = name.strip()
        if any(
            project.name.casefold() == name.casefold()
            for project in self.state.projects
        ):
            raise BrigError(f"Project '{name}' already exists. Choose another name.")
        return self._validate_name(name)

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
        agents: list[str] | None = None,
    ) -> Profile:
        name = self.validate_profile_name(name, editing=editing)
        selected_agents = [agent] if agents is None else agents
        validate_agents(selected_agents, agent)
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
                list(selected_agents),
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
        name = self.validate_project_name(name)
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

    def project_dockerfile(
        self, name: str | None, directory: Path, output: Path | None = None
    ) -> str:
        project = self.resolve_project(name, directory)
        contents = render_dockerfile(project)
        if output is None:
            return contents
        destination = write_dockerfile(output, contents)
        return f"Dockerfile exported to {destination}"

    def project_for_deletion(self, name: str) -> Project:
        project = self.project(name)
        if self.engine.has_running_resources(project):
            raise BrigError(
                f"Cannot delete running project '{project.name}'. Stop it first with 'brig down --project {project.name}'."
            )
        return project

    def delete_project(self, name: str) -> str:
        project = self.project_for_deletion(name)
        candidate = deepcopy(self.state)
        candidate.projects = [
            item for item in candidate.projects if item.id != project.id
        ]
        self._commit(candidate)
        return f"Deleted project '{project.name}' from Brig. Its local folder and profile were kept."

    def update_project(self, name: str) -> str:
        project = self.project(name)
        latest = self.profile(project.profile).latest
        if latest.number == project.configuration.number:
            return f"{project.name} already uses the latest profile revision."
        if self.engine.has_running_resources(project):
            raise BrigError("Stop the project before applying a profile update.")
        candidate = deepcopy(self.state)
        target = next(p for p in candidate.projects if p.id == project.id)
        target.configuration = deepcopy(latest)
        self._commit(candidate)
        return f"Updated {project.name} to profile revision {latest.number}."

    def start(self, name: str) -> str:
        return self._set_running(name, True)

    def project_status(self, project: Project) -> str:
        try:
            return "running" if self.engine.is_running(project) else "stopped"
        except BrigError:
            return "unknown (Docker unavailable)"

    def stop(self, name: str) -> str:
        return self._set_running(name, False)

    def run_agent(self, name: str, agent: str) -> str:
        validate_agent(agent)
        project = self.project(name)
        if agent not in project.configuration.selected_agents:
            raise BrigError(
                f"Agent '{agent}' is not selected in this project's profile."
            )
        self.engine.validate_shell()
        self.start(name)
        return self.engine.run_agent(self.project(name), agent)

    def shell(self, name: str, command=None) -> str:
        self.engine.validate_shell(command)
        self.start(name)
        return self.engine.shell(self.project(name), command)

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
        if len(name) > 64 or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name):
            raise BrigError(
                "Use kebab-case, e.g. laravel-project: a-z, 0-9 and single -; start with a letter. Max 64 chars."
            )
        return name
