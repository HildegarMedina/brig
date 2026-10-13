"""Coordinate the per-project Docker lifecycle and terminal execution."""

import os
import re
import subprocess
import sys
from pathlib import Path

from brig.components.agents import AGENTS, resolve_project_agent, validate_project_agent
from brig.docker.authentication import authenticate
from brig.docker.client import DockerClient
from brig.docker.compose import agent_history_volumes, project_prefix, render_compose
from brig.docker.credentials import DatabaseCredentials
from brig.docker.git_identity import host_git_identity, render_gitconfig
from brig.docker.isolation import agent_environment, agent_uid
from brig.docker.volumes import DockerVolumes
from brig.docker.workspace import DockerWorkspace
from brig.engine import Environment
from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Project


class DockerEngine:
    simulated = False

    def __init__(
        self, directory: Path, *, runner=None, uid=None, gid=None, git_runner=None
    ):
        self.directory = directory
        self.git_runner = git_runner or subprocess.run
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
        gitconfig = render_gitconfig(host_git_identity(project.path, self.git_runner))
        self.workspace.write_configuration(
            directory, project, credentials, dockerfile, compose, gitconfig
        )
        return directory, image

    def describe(self, project: Project) -> Environment:
        prefix = project_prefix(project)
        return Environment(
            f"{prefix}-dev",
            {name: f"{prefix}-{name}" for name in project.configuration.services},
            f"{prefix}-network",
            (f"{prefix}-work-home",)
            + tuple(
                f"{prefix}-{agent}-runtime-home"
                for agent in project.configuration.selected_agents
            )
            + tuple(
                f"{prefix}-credential-{agent}-{kind}"
                for agent in project.configuration.selected_agents
                for kind in ("ca", "view")
            )
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
            {agent: f"{prefix}-dev" for agent in project.configuration.selected_agents},
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
        for agent in project.configuration.selected_agents:
            self.client.inspect(project, agent=agent)
            self.client.inspect(project, agent=agent, proxy=True)
        directory, image = self.prepare(project)
        self.volumes.ensure_agent_volumes(project)
        command = self._compose(project, directory)
        missing = False
        for name in [
            image,
            f"{image}-credential-proxy",
        ]:
            found = self.client.run(["image", "inspect", name], check=False)
            if found.returncode:
                if "no such" not in (found.stderr or "").lower():
                    raise BrigError(
                        tr("Cannot inspect project image: ")
                        + (found.stderr or "").strip()
                    )
                missing = True
        if missing:
            print(
                tr("Building image for {value0}…").format(value0=project.name),
                file=sys.stderr,
                flush=True,
            )
            self.client.run(
                [
                    *command,
                    "build",
                    "dev",
                    f"credential_{project.configuration.selected_agents[0]}",
                ],
                capture=False,
            )
        print(
            tr("Starting {value0}…").format(value0=project.name),
            file=sys.stderr,
            flush=True,
        )
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
                tr(
                    "Docker reported success but the development container is not running."
                )
            )
        return tr(
            "Started {value0}. Use 'brig run {value1}' to enter its terminal."
        ).format(value0=project.name, value1=project.name)

    def clean(self, project: Project) -> str:
        with self.workspace.lock(project):
            self.client.check()
            _, current, _ = self.workspace.plan(project, self.uid, self.gid)
            repository = current.split(":", 1)[0]
            result = self.client.run(
                [
                    "image",
                    "ls",
                    "--no-trunc",
                    "--format",
                    "{{.ID}} {{.Repository}}:{{.Tag}}",
                ]
            )
            images = [line.split() for line in result.stdout.splitlines()]
            keep = {current, f"{current}-credential-proxy"}
            protected = {
                image_id for image_id, reference in images if reference in keep
            }
            pattern = re.compile(
                re.escape(repository)
                + r":[0-9a-f]{24}(?:-credential-proxy|-agent-(?:claude|codex|opencode))?"
            )
            removed = 0
            for image_id, reference in images:
                if image_id in protected or not pattern.fullmatch(reference):
                    continue
                containers = self.client.run(
                    [
                        "container",
                        "ls",
                        "--all",
                        "--filter",
                        f"ancestor={image_id}",
                        "--format",
                        "{{.ID}}",
                    ]
                )
                if containers.stdout.strip():
                    continue
                # Remove only the project's tag, without forcing deletion of shared images.
                self.client.run(["image", "rm", reference])
                removed += 1
            return tr(
                "Cleaned {value0}: removed {value1} old image tags. Current images, containers, and volumes were kept."
            ).format(value0=project.name, value1=removed)

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
                    tr(
                        "Cannot locate the managed Compose configuration for this container."
                    )
                )
            compose_dir = Path(config).parent
        else:
            files = sorted(
                directory.glob("*/compose.yaml"), key=lambda path: path.stat().st_mtime
            )
            if not files:
                return tr("{value0} is already stopped.").format(value0=project.name)
            compose_dir = files[-1].parent
        self.client.run(
            [*self._compose(project, compose_dir), "down", "--remove-orphans"],
            capture=False,
        )
        return tr(
            "Stopped {value0}. Source files and Docker volumes were kept."
        ).format(value0=project.name)

    def validate_shell(self, command=None) -> None:
        if not command and not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise BrigError(
                tr(
                    "Opening a project terminal requires an interactive terminal. Use '--command <program> [args...]' to run a command instead."
                )
            )

    def shell(self, project: Project, command=None, *, agent=None) -> str:
        agent = resolve_project_agent(project.configuration, agent)
        self.validate_shell(command)
        return self._execute(
            project, command or ["/bin/bash"], interactive=not command, agent=agent
        )

    def _execute(
        self, project: Project, command, *, interactive: bool, agent: str | None = None
    ) -> str:
        container = self.client.inspect(project)
        if not container or not container["State"]["Running"]:
            raise BrigError(
                tr(
                    "Project container is stopped. Run 'brig run' to start it and enter."
                )
            )
        args = ["docker", "exec", "--user", f"{agent_uid(agent, self.uid)}:{self.gid}"]
        for key, value in agent_environment(agent).items():
            args.extend(["--env", f"{key}={value}"])
        if interactive:
            args.append("-it")
        args.extend(
            [
                "--workdir",
                "/workspace",
                self.describe(project).agents[agent]
                if agent
                else self.describe(project).development,
                "/bin/sh",
                "-ec",
                '. "$HOME/.brig-environment.sh"; exec "$@"',
                "brig-session",
                *command,
            ]
        )
        try:
            result = self.client.runner(args, check=False)
        except OSError as error:
            raise BrigError(
                tr("Cannot enter project terminal: {value0}").format(value0=error)
            ) from error
        if result.returncode:
            raise BrigError(
                tr("Project command exited with status {value0}.").format(
                    value0=result.returncode
                )
            )
        return ""

    def run_agent(self, project: Project, agent: str, command=None) -> str:
        validate_project_agent(project.configuration, agent)
        self.validate_shell(command)
        return self._execute(
            project,
            command or list(AGENTS[agent].command),
            interactive=not command,
            agent=agent,
        )

    def authenticate_agent(self, project, agent, *, provider=None, key=None):
        validate_project_agent(project.configuration, agent)
        with self.workspace.lock(project):
            return authenticate(self, project, agent, provider=provider, key=key)
