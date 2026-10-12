"""Manual cleanup preserves current images and all container data."""

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock

from brig.application import Application
from brig.docker.engine import DockerEngine
from brig.errors import BrigError
from brig.ui.cli import dispatch, parser
from tests.fakes import MemoryStore, demo_state


class ImageCleanupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.project = demo_state().projects[1]
        self.engine = DockerEngine(Path(self.folder.name), uid=1000, gid=1000)
        _, self.current, _ = self.engine.workspace.plan(self.project, 1000, 1000)
        self.repository = self.current.split(":")[0]
        self.calls = []
        self.listing = ""
        self.used = set()
        self.fail = False

        def runner(args, **options):
            self.calls.append(args)
            if args[1:3] == ["image", "ls"]:
                return CompletedProcess(args, 0, self.listing, "")
            if args[1:3] == ["container", "ls"]:
                image_id = args[args.index("--filter") + 1].split("=", 1)[1]
                return CompletedProcess(
                    args, 0, "container" if image_id in self.used else "", ""
                )
            if self.fail and args[1:3] == ["image", "rm"]:
                return CompletedProcess(args, 1, "", "image is in use")
            return CompletedProcess(args, 0, "", "")

        self.engine.client.runner = runner

    def test_only_unused_old_project_tags_are_removed(self):
        old = f"{self.repository}:{'a' * 24}"
        proxy = old + "-credential-proxy"
        legacy = [old + "-agent-" + agent for agent in ("claude", "codex", "opencode")]
        used = f"{self.repository}:{'b' * 24}"
        alias = f"{self.repository}:{'c' * 24}"
        self.listing = "\n".join(
            [
                f"current {self.current}",
                f"proxy-current {self.current}-credential-proxy",
                f"current {alias}",
                f"proxy-current {alias}-credential-proxy",
                *[
                    f"legacy-{index} {reference}"
                    for index, reference in enumerate(legacy)
                ],
                f"old {old}",
                f"proxy {proxy}",
                f"used {used}",
                f"other {self.repository}-other:{'a' * 24}",
                "database postgres:17",
                f"invalid {self.repository}:latest",
            ]
        )
        self.used.add("used")
        message = self.engine.clean(self.project)
        self.assertIn("removed 5", message)
        self.assertEqual(
            [args for args in self.calls if args[1:3] == ["image", "rm"]],
            [
                ["docker", "image", "rm", reference]
                for reference in [*legacy, old, proxy]
            ],
        )
        self.assertTrue(
            all(
                "--all" in args
                for args in self.calls
                if args[1:3] == ["container", "ls"]
            )
        )
        self.assertFalse(
            any("volume" in args or "--force" in args for args in self.calls)
        )

    def test_empty_cleanup(self):
        self.assertIn("removed 0", self.engine.clean(self.project))

    def test_removal_error_is_reported_without_force(self):
        self.listing = f"old {self.repository}:{'a' * 24}"
        self.fail = True
        with self.assertRaisesRegex(BrigError, "image is in use"):
            self.engine.clean(self.project)

    def test_cli_dispatch_and_unknown_project(self):
        app = Application(MemoryStore(demo_state()), self.engine)
        self.engine.clean = Mock(return_value="cleaned")
        self.assertEqual(
            dispatch(app, parser().parse_args(["project", "clean", "api"])), "cleaned"
        )
        self.engine.clean.assert_called_once_with(app.project("api"))
        with self.assertRaises(BrigError):
            app.clean_project("missing")
