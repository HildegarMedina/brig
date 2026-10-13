"""Deleting a project removes only its own Docker resources and runtime files."""

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from brig.docker.compose import project_prefix
from brig.docker.engine import DockerEngine
from brig.errors import BrigError
from tests.fakes import demo_state


class ProjectRemovalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.project = demo_state().projects[1]
        self.other = demo_state().projects[0]
        self.engine = DockerEngine(Path(self.folder.name), uid=1000, gid=1000)
        self.prefix = project_prefix(self.project)
        other = project_prefix(self.other)
        self.calls = []
        self.dev = None
        label = f"label=org.brig.project-id={self.project.id}"
        listings = {
            ("container", True): "c1\nc2",
            ("network", True): f"{self.prefix}-network",
            ("network", False): "\n".join(
                [f"{self.prefix}-network", f"{self.prefix}-credential-claude", "bridge"]
            ),
            ("volume", True): f"{self.prefix}-work-home\n{self.prefix}-postgresql-data",
            ("volume", False): "\n".join(
                [
                    f"{self.prefix}-work-home",
                    f"{self.prefix}-postgresql-data",
                    f"{self.prefix}-legacy-agent-home",
                    f"{other}-work-home",
                    "brig-claude-1000-18b8caeed05b",
                ]
            ),
        }
        repository = f"brig-dev-{self.prefix}"

        def runner(args, **options):
            self.calls.append(args[1:])
            if args[1:3] == ["container", "inspect"]:
                if self.dev is None:
                    return CompletedProcess(args, 1, "", "Error: No such container")
                return CompletedProcess(args, 0, json.dumps([self.dev]), "")
            if args[2:3] == ["ls"] and args[1] != "image":
                return CompletedProcess(args, 0, listings[(args[1], label in args)], "")
            if args[1:3] == ["image", "ls"]:
                return CompletedProcess(
                    args,
                    0,
                    f"{repository}:{'a' * 24}\n{repository}:{'a' * 24}-credential-proxy",
                    "",
                )
            return CompletedProcess(args, 0, "", "")

        self.engine.client.runner = runner

    def test_only_project_resources_and_runtime_files_are_removed(self):
        runtime = self.engine.workspace.project_directory(self.project)
        (runtime / "digest").mkdir(parents=True)
        (runtime / "digest" / "credentials.json").write_text("{}")
        self.engine.remove(self.project)
        removals = [call for call in self.calls if call[1] == "rm"]
        repository = f"brig-dev-{self.prefix}"
        self.assertEqual(
            removals,
            [
                ["container", "rm", "--force", "c1", "c2"],
                [
                    "network",
                    "rm",
                    f"{self.prefix}-credential-claude",
                    f"{self.prefix}-network",
                ],
                [
                    "volume",
                    "rm",
                    f"{self.prefix}-legacy-agent-home",
                    f"{self.prefix}-postgresql-data",
                    f"{self.prefix}-work-home",
                ],
                [
                    "image",
                    "rm",
                    f"{repository}:{'a' * 24}",
                    f"{repository}:{'a' * 24}-credential-proxy",
                ],
            ],
        )
        self.assertFalse(runtime.exists())

    def test_running_project_is_stopped_before_removal(self):
        directory = self.engine.workspace.project_directory(self.project) / "digest"
        directory.mkdir(parents=True)
        (directory / "compose.yaml").write_text("services: {}\n")
        self.dev = {
            "State": {"Running": True},
            "Config": {
                "Labels": {
                    "org.brig.project-id": self.project.id,
                    "com.docker.compose.project.config_files": str(
                        directory / "compose.yaml"
                    ),
                }
            },
        }
        self.engine.remove(self.project)
        down = next(i for i, call in enumerate(self.calls) if "down" in call)
        first_removal = next(
            i for i, call in enumerate(self.calls) if call[1:2] == ["rm"]
        )
        self.assertLess(down, first_removal)

    def test_foreign_container_with_project_name_blocks_removal(self):
        self.dev = {
            "State": {"Running": True},
            "Config": {"Labels": {"org.brig.project-id": "someone-else"}},
        }
        with self.assertRaisesRegex(BrigError, "not managed by Brig"):
            self.engine.remove(self.project)
        self.assertFalse(any(call[1:2] == ["rm"] for call in self.calls))
