"""Bounded credential reading, shared locks, and atomic refresh persistence."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


class CredentialError(Exception):
    """Deliberately contains no token, file contents, or upstream error details."""


def read_json(path: Path):
    try:
        with path.open("rb") as stream:
            content = stream.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise CredentialError("Credential file is too large")
        return json.loads(content)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise CredentialError("Cannot read credentials") from error


def write_json(path: Path, value) -> None:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise CredentialError("Cannot persist credentials") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def credential_lock(directory: Path):
    try:
        with (directory / ".brig-auth.lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield
    except OSError as error:
        raise CredentialError("Cannot lock credential storage") from error
