"""Docker command boundary tests: real generated files, controlled subprocesses."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from brig.application import Application
from brig.docker.engine import DockerEngine
from brig.errors import BrigError
from brig.models import State
from tests.fakes import FakeVersionCatalog, MemoryStore


class DockerRunner:
    def __init__(self):
        self.calls = []
        self.running = False
        self.exists = False
        self.image = False
        self.failure = None
        self.owner = None
        self.project_id = None
        self.config = None
        self.volumes = ""
        self.volume_labels = None
        self.agent_volumes = {}

    def __call__(self, args, **options):
        self.calls.append((args, options))
        if self.failure and self.failure in args:
            return CompletedProcess(args, 1, "", "expected Docker failure")
        if args[1:3] == ["container", "inspect"]:
            if not self.exists:
                return CompletedProcess(args, 1, "", "Error: No such container")
            data = [
                {
                    "State": {"Running": self.running},
                    "Config": {
                        "Labels": {
                            "org.brig.project-id": self.owner or self.project_id,
                            **(
                                {"org.brig.agent": args[-1].split("-agent-")[-1]}
                                if "-agent-" in args[-1]
                                else {}
                            ),
                            "com.docker.compose.project.config_files": self.config,
                        }
                    },
                }
            ]
            return CompletedProcess(args, 0, json.dumps(data), "")
        if args[1:3] == ["image", "inspect"] and not self.image:
            return CompletedProcess(args, 1, "", "Error: No such image")
        if args[1:3] == ["container", "ls"]:
            return CompletedProcess(args, 0, "project-dev" if self.running else "", "")
        if args[1:3] == ["volume", "inspect"]:
            if args[-1].startswith(("brig-claude-", "brig-codex-", "brig-opencode-")):
                if args[-1] not in self.agent_volumes:
                    return CompletedProcess(args, 1, "", "Error: no such volume")
                return CompletedProcess(
                    args, 0, json.dumps([{"Labels": self.agent_volumes[args[-1]]}]), ""
                )
            if self.volume_labels is None:
                return CompletedProcess(args, 1, "", "Error: no such volume")
            return CompletedProcess(
                args, 0, json.dumps([{"Labels": self.volume_labels}]), ""
            )
        if args[1:3] == ["volume", "ls"]:
            return CompletedProcess(args, 0, self.volumes, "")
        if args[1:3] == ["volume", "create"]:
            self.agent_volumes[args[-1]] = dict(
                args[index + 1].split("=", 1)
                for index, value in enumerate(args)
                if value == "--label"
            )
        if "build" in args:
            self.image = True
        if "up" in args:
            self.exists = self.running = True
            self.config = args[args.index("--file") + 1]
        if "down" in args:
            self.exists = self.running = False
        return CompletedProcess(args, 0, "", "")


class DockerEngineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.runner = DockerRunner()
        self.engine = DockerEngine(
            Path(self.folder.name) / "runtime", runner=self.runner, uid=1234, gid=4321
        )
        self.store = MemoryStore(State())
        self.app = Application(self.store, self.engine, FakeVersionCatalog)
        self.app.save_profile(
            "python-dev",
            {"python": "3.12.8"},
            {},
            {"postgresql": "17.2", "redis": "7.4.2"},
        )
        source = Path(self.folder.name) / "project"
        source.mkdir()
        self.project = self.app.create_project("api", source, "python-dev")
        self.runner.project_id = self.project.id

    def start(self):
        with redirect_stderr(io.StringIO()):
            return self.app.start("api")

    def test_first_start_builds_then_waits_for_services_and_updates_state(self):
        self.start()
        commands = [args for args, _ in self.runner.calls]
        build = next(i for i, args in enumerate(commands) if "build" in args)
        up = next(i for i, args in enumerate(commands) if "up" in args)
        self.assertLess(build, up)
        self.assertIn("--wait", commands[up])
        self.assertIn("--no-build", commands[up])
        self.assertTrue(self.app.project("api").running)
        self.assertEqual(
            Path(self.runner.config).parent.joinpath(".dockerignore").read_text(),
            "*\n!Dockerfile\n",
        )
        self.assertFalse(Path(self.project.path).joinpath("Dockerfile").exists())

    def test_second_start_reuses_image_and_credentials_and_stop_preserves_volumes(self):
        self.start()
        directory = Path(self.runner.config).parent
        credentials = directory.parent / "credentials.json"
        before = credentials.read_text()
        self.runner.calls.clear()
        self.start()
        self.assertFalse(any("build" in args for args, _ in self.runner.calls))
        self.assertEqual(credentials.read_text(), before)
        self.assertEqual(credentials.stat().st_mode & 0o777, 0o600)
        with redirect_stderr(io.StringIO()):
            self.app.stop("api")
        down = next(args for args, _ in self.runner.calls if "down" in args)
        self.assertNotIn("--volumes", down)
        self.assertNotIn("-v", down)
        self.assertFalse(self.app.project("api").running)
        self.assertTrue(Path(self.project.path).is_dir())

    def test_run_prepares_and_executes_program_without_shell_interpolation(self):
        with redirect_stderr(io.StringIO()):
            self.app.shell("api", ["python", "-c", 'print("$HOME; literal")'])
        command, options = self.runner.calls[-1]
        self.assertEqual(command[1:4], ["exec", "--workdir", "/workspace"])
        self.assertEqual(command[-3:], ["python", "-c", 'print("$HOME; literal")'])
        self.assertNotIn("shell", options)
        self.assertNotIn("capture_output", options)
        self.assertTrue(self.app.project("api").running)

    def test_interactive_shell_uses_tty_and_rejects_pipelines_before_start(self):
        with (
            patch("brig.docker.engine.sys.stdin.isatty", return_value=False),
            self.assertRaisesRegex(BrigError, "interactive terminal"),
        ):
            self.app.shell("api")
        self.assertEqual(self.runner.calls, [])
        with (
            patch("brig.docker.engine.sys.stdin.isatty", return_value=True),
            patch("brig.docker.engine.sys.stdout.isatty", return_value=True),
            redirect_stderr(io.StringIO()),
        ):
            self.app.shell("api")
        command = self.runner.calls[-1][0]
        self.assertIn("-it", command)
        self.assertEqual(command[-1], "/bin/bash")

    def test_agent_prepares_project_and_launches_with_interactive_terminal(self):
        with (
            patch("brig.docker.engine.sys.stdin.isatty", return_value=True),
            patch("brig.docker.engine.sys.stdout.isatty", return_value=True),
            redirect_stderr(io.StringIO()),
        ):
            self.app.run_agent("api", "claude")
        self.assertEqual(
            self.runner.calls[-1][0],
            [
                "docker",
                "exec",
                "-it",
                "--workdir",
                "/workspace",
                self.engine.describe(self.project).agents["claude"],
                "claude",
            ],
        )
        self.assertTrue(self.app.project("api").running)

    def test_shared_agent_storage_rejects_unowned_volume(self):
        self.runner.agent_volumes[self.engine.agent_volume_name("claude")] = {}
        with self.assertRaisesRegex(BrigError, "not owned"):
            self.start()
        self.assertFalse(self.app.project("api").running)
        self.assertFalse(any("up" in args for args, _ in self.runner.calls))

    def test_shared_agent_storage_is_scoped_to_user_and_data_directory(self):
        self.start()
        name = self.engine.agent_volume_name("claude")
        self.assertEqual(self.runner.agent_volumes[name]["org.brig.uid"], "1234")
        same = DockerEngine(self.engine.directory, uid=1234, gid=4321)
        other = DockerEngine(
            self.engine.directory.parent / "another", uid=1234, gid=4321
        )
        other_user = DockerEngine(self.engine.directory, uid=5678, gid=4321)
        self.assertEqual(name, same.agent_volume_name("claude"))
        self.assertNotEqual(name, other.agent_volume_name("claude"))
        self.assertNotEqual(name, other_user.agent_volume_name("claude"))
        self.assertNotIn("org.brig.project-id", self.runner.agent_volumes[name])

    def test_invalid_agent_or_missing_terminal_does_not_start_containers(self):
        for agent, error in (
            ("unknown", "Unknown agent"),
            ("codex", "not selected"),
        ):
            with self.subTest(agent=agent), self.assertRaisesRegex(BrigError, error):
                self.app.run_agent("api", agent)
        with (
            patch("brig.docker.engine.sys.stdin.isatty", return_value=False),
            self.assertRaisesRegex(BrigError, "interactive terminal"),
        ):
            self.app.run_agent("api", "claude")
        self.assertEqual(self.runner.calls, [])

    def test_build_or_start_failure_never_marks_project_running(self):
        for failure in ("build", "up"):
            with self.subTest(failure=failure):
                self.runner.failure = failure
                self.runner.image = False
                with self.assertRaisesRegex(BrigError, "Docker failed"):
                    self.start()
                self.assertFalse(self.app.project("api").running)
                self.assertFalse(self.store.state.projects[0].running)

    def test_external_start_blocks_deletion_and_profile_updates_despite_stale_state(
        self,
    ):
        self.start()
        self.app.project("api").running = False
        self.app.save_profile("python-dev", {"python": "3.11.11"}, {}, {}, editing=True)
        with self.assertRaisesRegex(BrigError, "Stop the project"):
            self.app.update_project("api")
        with self.assertRaisesRegex(BrigError, "Cannot delete running"):
            self.app.delete_project("api")

    def test_missing_daemon_or_compose_reports_actionable_error_before_build(self):
        self.runner.failure = "version"
        with self.assertRaisesRegex(BrigError, "Cannot connect to Docker"):
            self.start()
        self.runner.failure = "compose"
        with self.assertRaisesRegex(BrigError, "Compose is unavailable"):
            self.start()
        with (
            patch("brig.docker.client.shutil.which", return_value=None),
            self.assertRaisesRegex(BrigError, "not installed"),
        ):
            DockerEngine(Path(self.folder.name)).start(self.project)

    def test_unowned_container_is_never_started_or_stopped(self):
        self.runner.exists = True
        self.runner.owner = "someone-else"
        for action in (self.app.start, self.app.stop):
            with self.assertRaisesRegex(BrigError, "not managed by Brig"):
                action("api")
        self.assertFalse(
            any("up" in args or "down" in args for args, _ in self.runner.calls)
        )

    def test_corrupt_or_missing_credentials_are_never_regenerated_over_existing_data(
        self,
    ):
        self.start()
        credentials = Path(self.runner.config).parent.parent / "credentials.json"
        credentials.write_text("broken")
        with self.assertRaisesRegex(BrigError, "Restore credentials"):
            self.start()
        self.assertEqual(credentials.read_text(), "broken")
        credentials.unlink()
        self.runner.volumes = "existing-project-data\n"
        with self.assertRaisesRegex(BrigError, "credentials are missing"):
            self.start()
        self.assertFalse(credentials.exists())

    def test_concurrent_lifecycle_operation_is_rejected(self):
        with (
            self.engine.workspace.lock(self.project),
            self.assertRaisesRegex(BrigError, "Another Brig operation"),
        ):
            self.start()

    def test_database_major_change_does_not_reinitialize_existing_volume(self):
        self.runner.volume_labels = {
            "org.brig.project-id": self.project.id,
            "org.brig.service-major": "16",
        }
        with self.assertRaisesRegex(BrigError, "data migration is required"):
            self.start()
        self.assertFalse(
            any("up" in args or "build" in args for args, _ in self.runner.calls)
        )

    def test_status_remains_readable_if_docker_is_unavailable(self):
        self.runner.failure = "version"
        self.assertEqual(
            self.app.project_status(self.project), "unknown (Docker unavailable)"
        )

    def test_profile_tool_change_selects_new_image_and_root_host_is_rejected(self):
        self.start()
        previous = self.runner.config
        self.app.project("api").configuration.tools["uv"] = "0.5.24"
        self.runner.image = False
        self.start()
        self.assertNotEqual(previous, self.runner.config)
        root = DockerEngine(Path(self.folder.name), runner=self.runner, uid=0, gid=0)
        with self.assertRaisesRegex(BrigError, "without sudo"):
            root.prepare(self.project)
