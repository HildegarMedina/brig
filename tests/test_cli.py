"""Command-level tests with isolated data and no interactive terminal."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from brig.cli import main


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name) / "data"

    def command(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(["--data-dir", str(self.data), *arguments])
        return status, output.getvalue(), errors.getvalue()

    def test_list_show_and_demo_execution(self):
        status, output, errors = self.command("profile", "list")
        self.assertEqual(status, 0)
        self.assertIn("Demo mode", output)
        self.assertIn("web-dev", output)
        self.assertEqual(errors, "")
        status, output, _ = self.command("project", "show", "website")
        self.assertEqual(status, 0)
        self.assertIn("no folder mounted", output)
        self.assertIn("not created", output)
        status, output, _ = self.command("up", "--project", "website")
        self.assertEqual(status, 0)
        self.assertIn("simulated", output)
        status, output, _ = self.command("run", "claude", "--project", "website")
        self.assertEqual(status, 0)
        self.assertIn("no agent was launched", output)
        self.assertEqual(self.command("shell", "--project", "website")[0], 0)
        self.assertEqual(self.command("down", "--project", "website")[0], 0)

    def test_project_resolution_error_is_actionable(self):
        with patch("brig.cli.Path.cwd", return_value=Path(self.directory.name)):
            status, _, errors = self.command("up")
        self.assertEqual(status, 1)
        self.assertIn("--project", errors)

    def test_future_agent_returns_error(self):
        status, _, errors = self.command("run", "codex", "--project", "api")
        self.assertEqual(status, 1)
        self.assertIn("future integration", errors)

    def test_noninteractive_wizards_fail_without_initializing_data(self):
        for arguments in (
            (),
            ("profile", "create"),
            ("profile", "edit", "web-dev"),
            ("project", "init"),
        ):
            with (
                self.subTest(arguments=arguments),
                patch("sys.stdin.isatty", return_value=False),
            ):
                status, _, errors = self.command(*arguments)
            self.assertEqual(status, 2)
            self.assertIn("interactive terminal", errors)
            self.assertFalse(self.data.exists())

    def test_invalid_data_is_not_replaced_by_command(self):
        self.data.mkdir()
        file = self.data / "state.json"
        file.write_text("broken")
        status, _, errors = self.command("project", "list")
        self.assertEqual(status, 1)
        self.assertIn("File was not changed", errors)
        self.assertEqual(file.read_text(), "broken")
