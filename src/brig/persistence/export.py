"""Atomic export of generated Dockerfiles without overwriting user files."""

import os
import tempfile
from pathlib import Path

from brig.errors import BrigError


def write_dockerfile(path: Path, contents: str) -> Path:
    """Publish a complete file atomically without replacing a user's existing file."""
    destination = path.expanduser().absolute()
    temporary = None
    try:
        if destination.exists() or destination.is_symlink():
            raise BrigError(
                f"Cannot export Dockerfile: {destination} already exists. Choose another output path."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=".brig-dockerfile-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError as error:
        raise BrigError(
            f"Cannot export Dockerfile: {destination} already exists. Choose another output path."
        ) from error
    except OSError as error:
        raise BrigError(
            f"Cannot export Dockerfile to {destination}: {error}"
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
