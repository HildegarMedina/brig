"""Private generated files, image cache keys and project lifecycle locks."""

import fcntl
import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from brig.docker.compose import project_prefix
from brig.docker.dockerfile import render_dockerfile
from brig.docker.services import service_environment
from brig.errors import BrigError


class DockerWorkspace:
    def __init__(self, directory: Path):
        self.directory = directory

    def project_directory(self, project):
        return self.directory.absolute() / project_prefix(project)

    @contextmanager
    def lock(self, project):
        path = self.project_directory(project) / "lifecycle.lock"
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as error:
            raise BrigError(f"Cannot lock project environment: {error}") from error
        with os.fdopen(descriptor, "w") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise BrigError(
                    f"Another Brig operation is preparing '{project.name}'. Retry after it finishes."
                ) from error
            yield

    @staticmethod
    def write(path: Path, contents: str):
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as error:
            raise BrigError(f"Cannot write Docker configuration: {error}") from error
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def env(values):
        return "".join(f"{key}={value}\n" for key, value in sorted(values.items()))

    def plan(self, project, uid, gid):
        if uid == 0 or gid == 0:
            raise BrigError(
                "Run Brig as your regular user, without sudo, so the project terminal can use an unprivileged user."
            )
        dockerfile = render_dockerfile(project)
        # Only image-affecting configuration contributes to the build cache key.
        digest = hashlib.sha256(f"{uid}:{gid}\n{dockerfile}".encode()).hexdigest()[:24]
        image = f"brig-dev-{project_prefix(project)}:{digest}"
        directory = self.project_directory(project) / digest
        return directory, image, dockerfile

    def write_configuration(self, directory, project, credentials, dockerfile, compose):
        environment = {}
        for name in sorted(project.configuration.services):
            initialization, connection = service_environment(name, **credentials[name])
            environment.update(connection)
            self.write(directory / f"{name}.env", self.env(initialization))
        self.write(directory / "development.env", self.env(environment))
        self.write(directory / "Dockerfile", dockerfile)
        self.write(directory / ".dockerignore", "*\n!Dockerfile\n")
        self.write(directory / "compose.yaml", compose)
