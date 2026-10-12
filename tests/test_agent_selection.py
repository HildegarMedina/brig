"""Host-side selection happens before Docker is touched, including cancellation."""

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from brig.errors import BrigError, Cancelled
from brig.ui.agent_selection import choose_agent
from brig.ui.cli import main
from tests import test_docker_engine
from tests.test_tui import ScriptedTerminal


class AgentSelectionTests(unittest.TestCase):
    def setUp(self):
        self.case = test_docker_engine.DockerEngineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.project = self.case.project

    def test_single_agent_and_explicit_choice_do_not_open_picker(self):
        self.assertEqual(choose_agent(self.project), "claude")
        self.project.configuration.agents = ["claude", "codex", "opencode"]
        self.assertEqual(choose_agent(self.project, "codex"), "codex")
        with self.assertRaisesRegex(BrigError, "not selected"):
            self.project.configuration.agents = ["claude"]
            choose_agent(self.project, "codex")

    def test_multiple_agents_require_choice_and_support_terminal_picker(self):
        self.project.configuration.agents = ["claude", "codex", "opencode"]
        with (
            patch("sys.stdin.isatty", return_value=False),
            self.assertRaises(BrigError),
        ):
            choose_agent(self.project)
        terminal = ScriptedTerminal(choices=[2])
        self.assertEqual(choose_agent(self.project, terminal=terminal), "opencode")
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch(
                "brig.ui.tui.terminal.Terminal",
                return_value=ScriptedTerminal(choices=[1]),
            ),
            patch(
                "brig.ui.agent_selection.curses.wrapper",
                side_effect=lambda pick: pick(object()),
            ),
        ):
            self.assertEqual(choose_agent(self.project), "codex")

    def test_cli_selection_cancellation_and_noninteractive_errors_precede_docker(self):
        self.project.configuration.agents = ["claude", "codex", "opencode"]
        with (
            patch("brig.ui.cli.Application", return_value=self.case.app),
            redirect_stderr(io.StringIO()),
        ):
            for arguments in (["run", "api"], ["agent", "--project", "api"]):
                with patch("brig.ui.cli.choose_agent", side_effect=Cancelled):
                    self.assertEqual(main(arguments), 130)
                with patch("sys.stdin.isatty", return_value=False):
                    self.assertEqual(main(arguments), 1)
        self.assertEqual(self.case.runner.calls, [])

    def test_run_and_shell_explicit_agent_execute_as_that_agent(self):
        self.project.configuration.agents = ["claude", "codex", "opencode"]
        with (
            patch("brig.ui.cli.Application", return_value=self.case.app),
            redirect_stderr(io.StringIO()),
        ):
            for arguments in (["run", "api"], ["shell", "--project", "api"]):
                self.assertEqual(
                    main(
                        [
                            *arguments,
                            "--agent",
                            "codex",
                            "--command",
                            "python",
                            "--version",
                        ]
                    ),
                    0,
                )
                command = self.case.runner.calls[-1][0]
                self.assertIn("HOME=/opt/brig-agent-home/codex", command)
                self.assertEqual(command[command.index("--user") + 1], "11235:4321")
