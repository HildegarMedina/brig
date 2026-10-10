"""Readable, portable YAML snapshots, with strings quoted to preserve versions."""

import json
from pathlib import Path
from urllib.parse import quote

from brig.components.catalog import SERVICES
from brig.models import ProfileVersion


def profile_path(directory: Path, name: str, version: int) -> Path:
    # Prefix also prevents names like '.' and '..' becoming path components.
    return (
        directory
        / "profiles"
        / f"profile-{quote(name, safe='')}"
        / "versions"
        / f"version-{version}.yaml"
    )


def render_profile(name: str, version: ProfileVersion) -> str:
    def scalar(value: str) -> str:
        return json.dumps(value, ensure_ascii=True)

    lines = [
        "# Brig profile · pinned versions",
        "schema_version: 2",
        f"name: {scalar(name)}",
        f"version: {version.number}",
    ]
    if version.extends:
        lines.extend(
            [
                "extends:",
                f"  profile: {scalar(version.extends.profile)}",
                f"  version: {version.extends.version}",
            ]
        )
    for section, selections in (
        ("runtimes", version.runtimes),
        ("tools", version.tools),
    ):
        lines.append(f"{section}:" if selections else f"{section}: {{}}")
        lines.extend(
            f"  {key}: {scalar(value)}" for key, value in sorted(selections.items())
        )
    databases = {
        key: value
        for key, value in version.services.items()
        if SERVICES[key].category != "Caches / key-value stores"
    }
    caches = {
        key: value
        for key, value in version.services.items()
        if SERVICES[key].category == "Caches / key-value stores"
    }
    for section, selections in (("databases", databases), ("caches", caches)):
        lines.append(f"{section}:" if selections else f"{section}: {{}}")
        lines.extend(
            f"  {key}: {scalar(value)}" for key, value in sorted(selections.items())
        )
    if version.agents is not None:
        lines.append("agents:")
        lines.extend(f"  - {scalar(agent)}" for agent in version.selected_agents)
    lines.append(f"agent: {scalar(version.agent)}")
    return "\n".join(lines) + "\n"


def legacy_profile(
    directory: Path, name: str, version: ProfileVersion
) -> tuple[Path, str]:
    """Check existing v1 YAML before creating a document in the new layout."""
    path = (
        profile_path(directory, name, version.number).parent.parent
        / f"revision-{version.number}.yaml"
    )
    contents = (
        render_profile(name, version)
        .replace("schema_version: 2", "schema_version: 1")
        .replace(f"\nversion: {version.number}\n", f"\nrevision: {version.number}\n")
    )
    return path, contents
