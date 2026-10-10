"""Readable, portable YAML snapshots, with strings quoted to preserve versions."""

import json
from pathlib import Path
from urllib.parse import quote

from brig.components.catalog import SERVICES
from brig.models import ProfileRevision


def profile_path(directory: Path, name: str, revision: int) -> Path:
    # Prefix also prevents names like '.' and '..' becoming path components.
    return (
        directory
        / "profiles"
        / f"profile-{quote(name, safe='')}"
        / f"revision-{revision}.yaml"
    )


def render_profile(name: str, revision: ProfileRevision) -> str:
    def scalar(value: str) -> str:
        return json.dumps(value, ensure_ascii=True)

    lines = [
        "# Brig profile · pinned versions",
        "schema_version: 1",
        f"name: {scalar(name)}",
        f"revision: {revision.number}",
    ]
    for section, selections in (
        ("runtimes", revision.runtimes),
        ("tools", revision.tools),
    ):
        lines.append(f"{section}:" if selections else f"{section}: {{}}")
        lines.extend(
            f"  {key}: {scalar(value)}" for key, value in sorted(selections.items())
        )
    databases = {
        key: value
        for key, value in revision.services.items()
        if SERVICES[key].category != "Caches / key-value stores"
    }
    caches = {
        key: value
        for key, value in revision.services.items()
        if SERVICES[key].category == "Caches / key-value stores"
    }
    for section, selections in (("databases", databases), ("caches", caches)):
        lines.append(f"{section}:" if selections else f"{section}: {{}}")
        lines.extend(
            f"  {key}: {scalar(value)}" for key, value in sorted(selections.items())
        )
    if revision.agents is not None:
        lines.append("agents:")
        lines.extend(f"  - {scalar(agent)}" for agent in revision.selected_agents)
    lines.append(f"agent: {scalar(revision.agent)}")
    return "\n".join(lines) + "\n"
