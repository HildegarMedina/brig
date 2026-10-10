"""Offline decoding and validation of versioned state records."""

from pathlib import Path

from brig.components.agents import validate_agents
from brig.components.catalog import validate_selection
from brig.i18n import tr
from brig.models import Profile, ProfileParent, ProfileVersion, Project, State
from brig.profile_inheritance import validate_relationships

SCHEMA_VERSION = 2


def decode_profile_version(raw: dict) -> ProfileVersion:
    record = dict(raw)
    if record.get("extends") is not None:
        record["extends"] = ProfileParent(**record["extends"])
    version = ProfileVersion(**record)
    if type(version.number) is not int or version.number < 1:
        raise ValueError(tr("Invalid version number"))
    for mapping in (version.runtimes, version.tools, version.services):
        if not isinstance(mapping, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
        ):
            raise ValueError(tr("Invalid version mapping"))
    validate_selection(version.runtimes, version.tools, version.services, version.agent)
    validate_agents(
        [version.agent] if version.agents is None else version.agents,
        version.agent,
    )
    return version


def validate_name(name: str) -> None:
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 64
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ValueError(tr("Invalid name"))


def decode_state(raw: dict) -> State:
    if set(raw) != {"schema_version", "profiles", "projects"}:
        raise ValueError(tr("Invalid state fields"))
    if type(raw["schema_version"]) is not int or raw["schema_version"] not in (
        1,
        SCHEMA_VERSION,
    ):
        raise ValueError(tr("Unsupported schema version"))
    if not isinstance(raw["profiles"], list) or not isinstance(raw["projects"], list):
        raise TypeError(tr("Profiles and projects must be lists"))
    profiles = []
    for item in raw["profiles"]:
        field = (
            "revisions"
            if raw["schema_version"] == 1 and "revisions" in item
            else "versions"
        )
        if set(item) != {"name", field}:
            raise ValueError(tr("Invalid profile fields"))
        versions = [decode_profile_version(r) for r in item[field]]
        if [r.number for r in versions] != list(
            range(1, len(versions) + 1)
        ) or not versions:
            raise ValueError(tr("Invalid version history"))
        profiles.append(Profile(item["name"], versions))
    projects = []
    for item in raw["projects"]:
        if set(item) != {"id", "name", "path", "profile", "configuration", "running"}:
            raise ValueError(tr("Invalid project fields"))
        record = dict(item)
        record["configuration"] = decode_profile_version(record["configuration"])
        project = Project(**record)
        if not isinstance(project.id, str) or not project.id:
            raise ValueError(tr("Invalid project ID"))
        if type(project.running) is not bool:
            raise ValueError(tr("Invalid project status"))
        if project.path is not None and (
            not isinstance(project.path, str) or not Path(project.path).is_absolute()
        ):
            raise ValueError(tr("Invalid project path"))
        projects.append(project)
    for records in (profiles, projects):
        names = [r.name for r in records]
        for name in names:
            validate_name(name)
        if len({n.casefold() for n in names}) != len(names):
            raise ValueError(tr("Duplicate names"))
    if len({p.id for p in projects}) != len(projects):
        raise ValueError(tr("Duplicate project IDs"))
    paths = [p.path for p in projects if p.path is not None]
    if len(set(paths)) != len(paths):
        raise ValueError(tr("Duplicate project paths"))
    validate_relationships(profiles)
    by_name = {p.name: p for p in profiles}
    for project in projects:
        profile = by_name.get(project.profile)
        if profile is None or project.configuration not in profile.versions:
            raise ValueError(tr("Project references an unknown profile version"))
    return State(profiles, projects)
