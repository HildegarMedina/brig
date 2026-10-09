"""Real per-project Docker Compose lifecycle and isolated terminal execution."""

import hashlib
import fcntl
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import contextmanager

from brig.compose import project_prefix, render_compose, service_environment
from brig.dockerfile import render_dockerfile
from brig.engine import Environment
from brig.errors import BrigError
from brig.models import Project


class DockerEngine:
    simulated = False

    def __init__(self, directory: Path, *, runner=None, uid=None, gid=None):
        self.directory = directory
        self.runner = runner or subprocess.run
        self.uid = os.getuid() if uid is None else uid
        self.gid = os.getgid() if gid is None else gid
        self._checked = False

    def describe(self, project: Project) -> Environment:
        prefix = project_prefix(project)
        return Environment(
            f"{prefix}-dev",
            {name: f"{prefix}-{name}" for name in project.configuration.services},
            f"{prefix}-network",
            (f"{prefix}-home",)
            + tuple(f"{prefix}-{name}-data" for name in project.configuration.services)
            + (
                (f"{prefix}-mongodb-config",)
                if "mongodb" in project.configuration.services
                else ()
            ),
        )

    def _run(self, args, *, capture=True, check=True):
        try:
            options = {"text": True, "check": False}
            if capture:
                options["capture_output"] = True
            else:
                options["stdout"] = sys.stderr
                options["stderr"] = sys.stderr
            result = self.runner(["docker", *args], **options)
        except FileNotFoundError as error:
            raise BrigError(
                "Docker is not installed. Install Docker Engine and its Compose plugin, then retry."
            ) from error
        except OSError as error:
            raise BrigError(f"Cannot execute Docker: {error}") from error
        if check and result.returncode:
            details = (
                result.stderr or result.stdout or "See Docker output above."
            ).strip()
            raise BrigError(f"Docker failed (exit {result.returncode}): {details}")
        return result

    def _check(self):
        if self._checked:
            return
        if self.runner is subprocess.run and not shutil.which("docker"):
            raise BrigError(
                "Docker is not installed. Install Docker Engine and its Compose plugin, then retry."
            )
        result = self._run(["version", "--format", "{{.Server.Version}}"], check=False)
        if result.returncode:
            raise BrigError(
                "Cannot connect to Docker. Start Docker and check your socket permissions. "
                + (result.stderr or "").strip()
            )
        result = self._run(["compose", "version", "--short"], check=False)
        if result.returncode:
            raise BrigError(
                "Docker Compose is unavailable. Install the Docker Compose v2 plugin."
            )
        self._checked = True

    def _inspect(self, project: Project):
        self._check()
        result = self._run(
            ["container", "inspect", self.describe(project).development], check=False
        )
        if result.returncode:
            if "no such" in (result.stderr or "").lower():
                return None
            raise BrigError(
                "Cannot inspect project container: " + (result.stderr or "").strip()
            )
        try:
            container = json.loads(result.stdout)[0]
            labels = container["Config"].get("Labels") or {}
            if labels.get("org.brig.project-id") != project.id:
                raise BrigError(
                    "A container with this project's name exists but is not managed by Brig. Resolve the name conflict before continuing."
                )
            return container
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise BrigError(
                "Docker returned an invalid container description."
            ) from error

    def is_running(self, project: Project) -> bool:
        container = self._inspect(project)
        return bool(container and container["State"]["Running"])

    def has_running_resources(self, project: Project) -> bool:
        self._check()
        result = self._run(
            [
                "container",
                "ls",
                "--filter",
                f"label=org.brig.project-id={project.id}",
                "--format",
                "{{.Names}}",
            ]
        )
        return bool(result.stdout.strip())

    def _check_data_versions(self, project):
        for name, version in project.configuration.services.items():
            volume = f"{project_prefix(project)}-{name}-data"
            result = self._run(["volume", "inspect", volume], check=False)
            if result.returncode and "no such" in (result.stderr or "").lower():
                continue
            if result.returncode:
                raise BrigError(
                    "Cannot inspect project data volume: "
                    + (result.stderr or "").strip()
                )
            try:
                labels = json.loads(result.stdout)[0].get("Labels") or {}
                if labels.get("org.brig.project-id") != project.id:
                    raise BrigError(
                        f"Data volume '{volume}' is not managed by this project."
                    )
                if labels.get("org.brig.service-major") != version.split(".")[0]:
                    raise BrigError(
                        f"Cannot start {name} {version} with this project's existing data volume. A major-version data migration is required; Brig will not overwrite or reinitialize it."
                    )
            except (ValueError, IndexError, KeyError, TypeError) as error:
                raise BrigError(
                    "Docker returned an invalid data volume description."
                ) from error

    def _project_directory(self, project):
        return self.directory.absolute() / project_prefix(project)

    @contextmanager
    def _lock(self, project):
        path = self._project_directory(project) / "lifecycle.lock"
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
    def _write(path: Path, contents: str):
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

    def _credentials(self, project):
        path = self._project_directory(project) / "credentials.json"
        if path.exists():
            try:
                credentials = json.loads(path.read_text())
                if not isinstance(credentials, dict) or any(
                    not isinstance(pair, dict)
                    or set(pair) != {"password", "root_password"}
                    or any(
                        not isinstance(value, str)
                        or not value.isalnum()
                        or len(value) < 24
                        for value in pair.values()
                    )
                    for pair in credentials.values()
                ):
                    raise ValueError("Invalid credentials")
            except (OSError, ValueError) as error:
                raise BrigError(
                    "Cannot read project database credentials. Restore credentials.json from backup; passwords will not be silently replaced."
                ) from error
        else:
            credentials = {}
            # Existing volumes without credentials cannot be safely reinitialized.
            result = self._run(
                [
                    "volume",
                    "ls",
                    "--filter",
                    f"label=org.brig.project-id={project.id}",
                    "--format",
                    "{{.Name}}",
                ]
            )
            if result.stdout.strip():
                raise BrigError(
                    "Project volumes exist but database credentials are missing. Restore the project's credentials.json before starting it."
                )
        changed = not path.exists()
        for name in project.configuration.services:
            if name not in credentials:
                credentials[name] = {
                    "password": secrets.token_hex(24),
                    "root_password": secrets.token_hex(24),
                }
                changed = True
        if changed:
            self._write(path, json.dumps(credentials, indent=2) + "\n")
        return credentials

    def prepare(self, project):
        if self.uid == 0 or self.gid == 0:
            raise BrigError(
                "Run Brig as your regular user, without sudo, so the project terminal can use an unprivileged user."
            )
        dockerfile = render_dockerfile(project)
        # Only image-affecting configuration contributes to the build cache key.
        digest = hashlib.sha256(
            f"{self.uid}:{self.gid}\n{dockerfile}".encode()
        ).hexdigest()[:24]
        image = f"brig-dev-{project_prefix(project)}:{digest}"
        compose = render_compose(project, image, self.uid, self.gid)
        self._check()
        self._check_data_versions(project)
        credentials = self._credentials(project)
        directory = self._project_directory(project) / digest
        environment = {}
        for name in sorted(project.configuration.services):
            initialization, connection = service_environment(name, **credentials[name])
            environment.update(connection)
            self._write(directory / f"{name}.env", self._env(initialization))
        self._write(directory / "development.env", self._env(environment))
        self._write(directory / "Dockerfile", dockerfile)
        self._write(directory / ".dockerignore", "*\n!Dockerfile\n")
        self._write(directory / "compose.yaml", compose)
        return directory, image

    @staticmethod
    def _env(values):
        return "".join(f"{key}={value}\n" for key, value in sorted(values.items()))

    @staticmethod
    def _compose(project, directory):
        return [
            "compose",
            "--project-name",
            project_prefix(project),
            "--project-directory",
            str(directory),
            "--env-file",
            "/dev/null",
            "--file",
            str(directory / "compose.yaml"),
        ]

    def start(self, project: Project) -> str:
        with self._lock(project):
            return self._start(project)

    def _start(self, project: Project) -> str:
        self._inspect(project)  # Verify ownership before making changes.
        directory, image = self.prepare(project)
        command = self._compose(project, directory)
        found = self._run(["image", "inspect", image], check=False)
        if found.returncode:
            if "no such" not in (found.stderr or "").lower():
                raise BrigError(
                    "Cannot inspect project image: " + (found.stderr or "").strip()
                )
            print(f"Building image for {project.name}…", file=sys.stderr, flush=True)
            self._run([*command, "build", "dev"], capture=False)
        print(f"Starting {project.name}…", file=sys.stderr, flush=True)
        self._run(
            [
                *command,
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "360",
                "--remove-orphans",
            ],
            capture=False,
        )
        if not self.is_running(project):
            raise BrigError(
                "Docker reported success but the development container is not running."
            )
        return f"Started {project.name}. Use 'brig run {project.name}' to enter its terminal."

    def stop(self, project: Project) -> str:
        with self._lock(project):
            return self._stop(project)

    def _stop(self, project: Project) -> str:
        container = self._inspect(project)
        directory = self._project_directory(project)
        if container:
            config = (container["Config"].get("Labels") or {}).get(
                "com.docker.compose.project.config_files"
            )
            if not config or Path(config).parent.parent != directory:
                raise BrigError(
                    "Cannot locate the managed Compose configuration for this container."
                )
            compose_dir = Path(config).parent
        else:
            files = sorted(
                directory.glob("*/compose.yaml"), key=lambda path: path.stat().st_mtime
            )
            if not files:
                return f"{project.name} is already stopped."
            compose_dir = files[-1].parent
        self._run(
            [*self._compose(project, compose_dir), "down", "--remove-orphans"],
            capture=False,
        )
        return f"Stopped {project.name}. Source files and Docker volumes were kept."

    def validate_shell(self, command=None) -> None:
        if not command and not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise BrigError(
                "Opening a project terminal requires an interactive terminal. Use '--command <program> [args...]' to run a command instead."
            )

    def shell(self, project: Project, command=None) -> str:
        self.validate_shell(command)
        container = self._inspect(project)
        if not container or not container["State"]["Running"]:
            raise BrigError(
                "Project container is stopped. Run 'brig run' to start it and enter."
            )
        args = ["docker", "exec"]
        if not command:
            args.append("-it")
        args.extend(
            [
                "--workdir",
                "/workspace",
                self.describe(project).development,
                *(command or ["/bin/bash"]),
            ]
        )
        try:
            result = self.runner(args, check=False)
        except OSError as error:
            raise BrigError(f"Cannot enter project terminal: {error}") from error
        if result.returncode:
            raise BrigError(f"Project command exited with status {result.returncode}.")
        return ""

    def run_agent(self, project: Project, agent: str) -> str:
        raise BrigError(
            f"Agent '{agent}' is not installed by Brig yet. Use 'brig run {project.name}' to enter the project terminal."
        )
