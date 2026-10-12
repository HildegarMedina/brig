"""Docker subprocess execution, availability and container inspection."""

import json
import shutil
import subprocess
import sys

from brig.docker.compose import project_prefix
from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Project


class DockerClient:
    def __init__(self, runner=None):
        self.runner = runner or subprocess.run
        self._checked = False

    def run(self, args, *, capture=True, check=True):
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
                tr(
                    "Docker is not installed. Install Docker Engine and its Compose plugin, then retry."
                )
            ) from error
        except OSError as error:
            raise BrigError(
                tr("Cannot execute Docker: {value0}").format(value0=error)
            ) from error
        if check and result.returncode:
            details = (
                result.stderr or result.stdout or "See Docker output above."
            ).strip()
            raise BrigError(
                tr("Docker failed (exit {value0}): {value1}").format(
                    value0=result.returncode, value1=details
                )
            )
        return result

    def check(self):
        if self._checked:
            return
        if self.runner is subprocess.run and not shutil.which("docker"):
            raise BrigError(
                tr(
                    "Docker is not installed. Install Docker Engine and its Compose plugin, then retry."
                )
            )
        result = self.run(["version", "--format", "{{.Server.Version}}"], check=False)
        if result.returncode:
            raise BrigError(
                tr(
                    "Cannot connect to Docker. Start Docker and check your socket permissions. "
                )
                + (result.stderr or "").strip()
            )
        result = self.run(["compose", "version", "--short"], check=False)
        if result.returncode:
            raise BrigError(
                tr(
                    "Docker Compose is unavailable. Install the Docker Compose v2 plugin."
                )
            )
        self._checked = True

    def inspect(self, project: Project, *, agent: str | None = None):
        self.check()
        result = self.run(
            [
                "container",
                "inspect",
                f"{project_prefix(project)}-agent-{agent}"
                if agent
                else f"{project_prefix(project)}-dev",
            ],
            check=False,
        )
        if result.returncode:
            if "no such" in (result.stderr or "").lower():
                return None
            raise BrigError(
                tr("Cannot inspect project container: ") + (result.stderr or "").strip()
            )
        try:
            container = json.loads(result.stdout)[0]
            labels = container["Config"].get("Labels") or {}
            if labels.get("org.brig.project-id") != project.id or (
                agent is not None and labels.get("org.brig.agent") != agent
            ):
                raise BrigError(
                    tr(
                        "A container with this project's name exists but is not managed by Brig. Resolve the name conflict before continuing."
                    )
                )
            return container
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise BrigError(
                tr("Docker returned an invalid container description.")
            ) from error

    def has_running_resources(self, project: Project) -> bool:
        self.check()
        result = self.run(
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
