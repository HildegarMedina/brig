"""Offline decoding and validation of versioned state records."""

from pathlib import Path

from brig.components.agents import validate_agents
from brig.components.catalog import validate_selection
from brig.models import Profile, ProfileRevision, Project, State

SCHEMA_VERSION = 1


def _revision(raw: dict) -> ProfileRevision:
    revision = ProfileRevision(**raw)
    if type(revision.number) is not int or revision.number < 1:
        raise ValueError("Invalid revision number")
    for mapping in (revision.runtimes, revision.tools, revision.services):
        if not isinstance(mapping, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
        ):
            raise ValueError("Invalid version mapping")
    validate_selection(
        revision.runtimes, revision.tools, revision.services, revision.agent
    )
    validate_agents(
        [revision.agent] if revision.agents is None else revision.agents,
        revision.agent,
    )
    return revision


def decode_state(raw: dict) -> State:
    if set(raw) != {"schema_version", "profiles", "projects"}:
        raise ValueError("Invalid state fields")
    if (
        type(raw["schema_version"]) is not int
        or raw["schema_version"] != SCHEMA_VERSION
    ):
        raise ValueError("Unsupported schema version")
    if not isinstance(raw["profiles"], list) or not isinstance(raw["projects"], list):
        raise TypeError("Profiles and projects must be lists")
    profiles = []
    for item in raw["profiles"]:
        if set(item) != {"name", "revisions"}:
            raise ValueError("Invalid profile fields")
        revisions = [_revision(r) for r in item["revisions"]]
        if [r.number for r in revisions] != list(
            range(1, len(revisions) + 1)
        ) or not revisions:
            raise ValueError("Invalid revision history")
        profiles.append(Profile(item["name"], revisions))
    projects = []
    for item in raw["projects"]:
        if set(item) != {"id", "name", "path", "profile", "configuration", "running"}:
            raise ValueError("Invalid project fields")
        record = dict(item)
        record["configuration"] = _revision(record["configuration"])
        project = Project(**record)
        if not isinstance(project.id, str) or not project.id:
            raise ValueError("Invalid project ID")
        if type(project.running) is not bool:
            raise ValueError("Invalid project status")
        if project.path is not None and (
            not isinstance(project.path, str) or not Path(project.path).is_absolute()
        ):
            raise ValueError("Invalid project path")
        projects.append(project)
    for records in (profiles, projects):
        names = [r.name for r in records]
        if any(
            not isinstance(n, str)
            or not n.strip()
            or len(n) > 64
            or any(ord(c) < 32 or ord(c) == 127 for c in n)
            for n in names
        ):
            raise ValueError("Invalid name")
        if len({n.casefold() for n in names}) != len(names):
            raise ValueError("Duplicate names")
    if len({p.id for p in projects}) != len(projects):
        raise ValueError("Duplicate project IDs")
    paths = [p.path for p in projects if p.path is not None]
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate project paths")
    by_name = {p.name: p for p in profiles}
    for project in projects:
        profile = by_name.get(project.profile)
        if profile is None or project.configuration not in profile.revisions:
            raise ValueError("Project references an unknown profile revision")
    return State(profiles, projects)
