"""Atomic export of generated Dockerfiles without overwriting user files."""

import os
import tempfile
from pathlib import Path

from brig.errors import BrigError
from brig.i18n import tr


def write_dockerfile(path: Path, contents: str) -> Path:
    """Publish a complete file atomically without replacing a user's existing file."""
    destination = path.expanduser().absolute()
    temporary = None
    try:
        if destination.exists() or destination.is_symlink():
            raise BrigError(
                tr(
                    "Cannot export Dockerfile: {value0} already exists. Choose another output path."
                ).format(value0=destination)
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
            tr(
                "Cannot export Dockerfile: {value0} already exists. Choose another output path."
            ).format(value0=destination)
        ) from error
    except OSError as error:
        raise BrigError(
            tr("Cannot export Dockerfile to {value0}: {value1}").format(
                value0=destination, value1=error
            )
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
