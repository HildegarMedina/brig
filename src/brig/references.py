"""Persistent host directory references, exposed only through read-only binds."""

import re
from pathlib import Path

from brig.errors import BrigError
from brig.i18n import tr

REFERENCES_PATH = "/references"


def valid_alias(value):
    return (
        isinstance(value, str)
        and len(value) <= 64
        and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value) is not None
    )


def validate_references(values):
    if not isinstance(values, dict) or any(
        not valid_alias(alias)
        or not isinstance(path, str)
        or not Path(path).is_absolute()
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
        for alias, path in values.items()
    ):
        raise ValueError(tr("Invalid project references."))


def reference_source(project, path):
    try:
        source = path.expanduser().resolve(strict=True)
        if not source.is_dir() or any(
            ord(char) < 32 or ord(char) == 127 for char in str(source)
        ):
            raise ValueError("not a directory")
    except (OSError, RuntimeError, ValueError) as error:
        raise BrigError(
            tr("Reference must be an accessible existing directory: {path}.").format(
                path=path
            )
        ) from error
    if project.path:
        workspace = Path(project.path).resolve()
        if source.is_relative_to(workspace) or workspace.is_relative_to(source):
            raise BrigError(
                tr("Reference must be outside the project's folder and its parents.")
            )
    return str(source)


def reference_mounts(project):
    validate_references(project.references)
    mounts = []
    for alias, path in sorted(project.references.items()):
        # Resolve on registration, then reject later symlink replacement rather
        # than silently exposing a different directory after a restart.
        if reference_source(project, Path(path)) != path:
            raise BrigError(
                tr("Reference directory changed its destination: {path}.").format(
                    path=path
                )
            )
        mounts.append(
            {
                "type": "bind",
                "source": path,
                "target": f"{REFERENCES_PATH}/{alias}",
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        )
    return mounts


def references_match(project, container):
    mounted = {
        mount["Destination"]: (mount.get("Source"), mount.get("RW", True))
        for mount in container.get("Mounts", [])
        if mount.get("Destination", "").startswith(f"{REFERENCES_PATH}/")
    }
    expected = {
        f"{REFERENCES_PATH}/{alias}": (path, False)
        for alias, path in project.references.items()
    }
    return mounted == expected
