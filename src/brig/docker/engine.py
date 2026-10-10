"""Coordinate the per-project Docker lifecycle and terminal execution."""

import os
import sys
from pathlib import Path

from brig.components.agents import AGENTS, validate_agent
from brig.docker.client import DockerClient
from brig.docker.compose import agent_history_volumes, project_prefix, render_compose
from brig.docker.credentials import DatabaseCredentials
from brig.docker.volumes import DockerVolumes
from brig.docker.workspace import DockerWorkspace
from brig.engine import Environment
from brig.errors import BrigError
from brig.models import Project


class DockerEngine:
    simulated = False

    def __init__(self, directory: Path, *, runner=None, uid=None, gid=None):
        self.directory = directory
        self.uid = os.getuid() if uid is None else uid
        self.gid = os.getgid() if gid is None else gid
        self.client = DockerClient(runner)
        self.workspace = DockerWorkspace(directory)
        self.volumes = DockerVolumes(self.client, directory, self.uid)
        self.credentials = DatabaseCredentials(self.client, self.workspace)

    def agent_volume_name(self, agent: str) -> str:
        return self.volumes.agent_volume_name(agent)

    def has_running_resources(self, project: Project) -> bool:
        return self.client.has_running_resources(project)

    def prepare(self, project):
        directory, image, dockerfile = self.workspace.plan(project, self.uid, self.gid)
        compose = render_compose(
            project,
            image,
            self.uid,
            self.gid,
            agent_volumes={
                agent: self.agent_volume_name(agent)
                for agent in project.configuration.selected_agents
            },
        )
        self.client.check()
        self.volumes.check_data_versions(project)
        credentials = self.credentials.load(project)
        self.workspace.write_configuration(
            directory, project, credentials, dockerfile, compose
        )
        return directory, image

    def describe(self, project: Project) -> Environment:
        prefix = project_prefix(project)
        return Environment(
            f"{prefix}-dev",
            {name: f"{prefix}-{name}" for name in project.configuration.services},
            f"{prefix}-network",
            (f"{prefix}-home",)
            + tuple(
                volume
                for agent in project.configuration.selected_agents
                if AGENTS[agent].config_directory
                for volume in (self.agent_volume_name(agent),)
                + tuple(
                    volume for _, volume, _ in agent_history_volumes(project, agent)
                )
            )
            + tuple(f"{prefix}-{name}-data" for name in project.configuration.services)
            + (
                (f"{prefix}-mongodb-config",)
                if "mongodb" in project.configuration.services
                else ()
            ),
        )

    def is_running(self, project: Project) -> bool:
        container = self.client.inspect(project)
        return bool(container and container["State"]["Running"])

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
        with self.workspace.lock(project):
            return self._start(project)

    def _start(self, project: Project) -> str:
        self.client.inspect(project)  # Verify ownership before making changes.
        directory, image = self.prepare(project)
        self.volumes.ensure_agent_volumes(project)
        command = self._compose(project, directory)
        found = self.client.run(["image", "inspect", image], check=False)
        if found.returncode:
            if "no such" not in (found.stderr or "").lower():
                raise BrigError(
                    "Cannot inspect project image: " + (found.stderr or "").strip()
                )
            print(f"Building image for {project.name}…", file=sys.stderr, flush=True)
            self.client.run([*command, "build", "dev"], capture=False)
        print(f"Starting {project.name}…", file=sys.stderr, flush=True)
        self.client.run(
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
        with self.workspace.lock(project):
            return self._stop(project)

    def _stop(self, project: Project) -> str:
        container = self.client.inspect(project)
        directory = self.workspace.project_directory(project)
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
        self.client.run(
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
        return self._execute(project, command or ["/bin/bash"], interactive=not command)

    def _execute(self, project: Project, command, *, interactive: bool) -> str:
        container = self.client.inspect(project)
        if not container or not container["State"]["Running"]:
            raise BrigError(
                "Project container is stopped. Run 'brig run' to start it and enter."
            )
        args = ["docker", "exec"]
        if interactive:
            args.append("-it")
        args.extend(
            [
                "--workdir",
                "/workspace",
                self.describe(project).development,
                *command,
            ]
        )
        try:
            result = self.client.runner(args, check=False)
        except OSError as error:
            raise BrigError(f"Cannot enter project terminal: {error}") from error
        if result.returncode:
            raise BrigError(f"Project command exited with status {result.returncode}.")
        return ""

    def run_agent(self, project: Project, agent: str) -> str:
        validate_agent(agent)
        if agent not in project.configuration.selected_agents:
            raise BrigError(
                f"Agent '{agent}' is not selected in this project's profile."
            )
        self.validate_shell()
        return self._execute(project, list(AGENTS[agent].command), interactive=True)
