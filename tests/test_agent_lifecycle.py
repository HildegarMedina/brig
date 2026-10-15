"""Agent launch, protected first login, release checks and safe image updates."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

from brig.agent_updates import newer, releases, version_number
from brig.auth_proxy.maintenance import configured
from brig.auth_proxy.storage import write_json
from brig.errors import BrigError, Cancelled, PendingReferences
from brig.ui import sessions
from brig.ui.cli import main
from tests import test_docker_engine
from tests.test_tui import ScriptedTerminal


class AgentReleaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_stable_sources_cache_expiry_and_explicit_refresh(self):
        def fetch(url):
            return json.dumps({"tag_name": "v2.3.4", "version": "2.3.4"})

        source = Mock(side_effect=fetch)
        agents = ["claude", "codex", "opencode"]
        self.assertEqual(
            releases(self.root, agents, fetch=source, now=100),
            dict.fromkeys(agents, "2.3.4"),
        )
        self.assertIn("/stable", source.call_args_list[0].args[0])
        self.assertEqual(
            releases(self.root, agents, fetch=source, now=101),
            dict.fromkeys(agents, "2.3.4"),
        )
        self.assertEqual(source.call_count, 3)
        releases(self.root, agents, fetch=source, now=86500)
        self.assertEqual(source.call_count, 6)
        releases(self.root, agents, fetch=source, now=86501, force=True)
        self.assertEqual(source.call_count, 9)
        self.assertTrue(newer("1.10.0", "1.9.0"))
        self.assertFalse(newer("1.0.0", "2.0.0"))
        self.assertEqual(version_number("codex-cli 1.2.3"), "1.2.3")
        with self.assertRaises(ValueError):
            version_number("unknown")

    def test_bad_cache_is_refetched_and_network_failure_does_not_invent_versions(self):
        path = self.root / "agent-release-cache.json"
        for data in (
            "[]",
            "not json",
            '{"codex": null}',
            '{"codex":{"checked":100,"version":"bad"}}',
        ):
            path.write_text(data)
            self.assertEqual(
                releases(
                    self.root, ["codex"], fetch=lambda _: '{"version":"1.2.3"}', now=101
                ),
                {"codex": "1.2.3"},
            )
        for result in (OSError("offline"), "{}", '{"version":7}'):
            fetch = (
                Mock(side_effect=result)
                if isinstance(result, Exception)
                else Mock(return_value=result)
            )
            with self.assertRaisesRegex(BrigError, "Cannot check"):
                releases(self.root, ["codex"], force=True, fetch=fetch)

    def test_credentials_presence_never_refreshes_or_exports_tokens(self):
        self.assertFalse(configured(self.root, "claude"))
        write_json(
            self.root / "brig-auth.json",
            {"anthropic": {"type": "api", "key": "fixture-secret-key"}},
        )
        self.assertTrue(configured(self.root, "claude"))
        self.assertFalse(configured(self.root, "codex"))
        write_json(
            self.root / "brig-auth.json",
            {"google": {"type": "oauth", "access": "fixture-access-token"}},
        )
        self.assertTrue(configured(self.root, "opencode"))
        write_json(self.root / "brig-auth.json", {"google": None})
        self.assertFalse(configured(self.root, "opencode"))


class AgentDockerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.case = test_docker_engine.DockerEngineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.engine = self.case.engine
        self.project = self.case.project

    def test_login_probe_has_readonly_protected_volume_and_no_workspace(self):
        self.assertTrue(self.engine.has_credentials(self.project, "claude"))
        args = self.case.runner.calls[-1][0]
        self.assertIn("--read-only", args)
        self.assertIn("none", args)
        self.assertTrue(any("target=/secrets,readonly" in arg for arg in args))
        self.assertNotIn("/workspace", " ".join(args))
        self.assertNotIn("-it", args)
        with patch.object(
            self.engine.client, "run", return_value=CompletedProcess([], 3)
        ):
            self.assertFalse(self.engine.has_credentials(self.project, "claude"))
        with (
            patch.object(
                self.engine.client, "run", return_value=CompletedProcess([], 1)
            ),
            self.assertRaisesRegex(BrigError, "Cannot inspect"),
        ):
            self.engine.has_credentials(self.project, "claude")

    def test_installed_versions_are_read_without_agent_credentials(self):
        with patch.object(
            self.engine.client,
            "run",
            return_value=CompletedProcess([], 0, "2.3.4 (Claude Code)"),
        ) as run:
            self.assertEqual(
                self.engine.agent_versions(self.project), {"claude": "2.3.4"}
            )
        args = run.call_args.args[0]
        self.assertNotIn("--mount", args)
        self.assertIn("--read-only", args)
        # OpenCode creates ~/.local/share/opencode even for --version.
        self.assertEqual(args[args.index("--tmpfs") + 1], "/home/brig:mode=1777")
        self.assertIn("HOME=/home/brig", args)
        with (
            patch.object(
                self.engine.client,
                "run",
                return_value=CompletedProcess([], 0, "invalid"),
            ),
            self.assertRaisesRegex(BrigError, "Cannot read installed"),
        ):
            self.engine.agent_versions(self.project)

    def test_update_builds_separate_image_before_switching_and_reuses_volumes(self):
        previous_dir, previous_image, _ = self.engine.workspace.plan(
            self.project, 1234, 4321
        )
        with patch.object(
            self.engine, "agent_versions", return_value={"claude": "2.3.4"}
        ):
            self.assertIn(
                "updates applied",
                self.case.app.update_agents("api", {"claude": "2.3.4"}),
            )
        directory, image, dockerfile = self.engine.workspace.plan(
            self.project, 1234, 4321
        )
        self.assertNotEqual(image, previous_image)
        self.assertNotEqual(directory, previous_dir)
        self.assertIn("ARG BRIG_AGENT_RELEASE=2.3.4", dockerfile)
        self.assertEqual(
            self.engine.workspace.agent_releases(self.project), {"claude": "2.3.4"}
        )
        commands = [call[0] for call in self.case.runner.calls]
        self.assertLess(
            next(i for i, c in enumerate(commands) if "build" in c),
            next(i for i, c in enumerate(commands) if "up" in c),
        )
        self.assertFalse(
            any(
                "--volumes" in command or "--no-cache" in command
                for command in commands
            )
        )
        self.assertTrue(self.case.app.project("api").running)

    def test_failed_build_or_wrong_release_preserves_current_image_selection(self):
        before = self.engine.workspace.plan(self.project, 1234, 4321)[1]
        self.case.runner.failure = "build"
        with self.assertRaises(BrigError):
            self.engine.update_agents(self.project, {"claude": "2.3.4"})
        self.case.runner.failure = None
        with (
            patch.object(
                self.engine, "agent_versions", return_value={"claude": "1.0.0"}
            ),
            self.assertRaisesRegex(BrigError, "previous image was kept"),
        ):
            self.engine.update_agents(self.project, {"claude": "2.3.4"})
        self.assertEqual(
            self.engine.workspace.plan(self.project, 1234, 4321)[1], before
        )
        self.assertFalse(any("up" in args for args, _ in self.case.runner.calls))

    def test_invalid_persisted_release_selection_is_actionable(self):
        path = (
            self.engine.workspace.project_directory(self.project)
            / "agent-releases.json"
        )
        path.parent.mkdir(parents=True)
        for value in ([], {"claude": "bad"}, {"evil": "1.2.3"}, {"claude": 7}):
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(BrigError, "release selection"):
                self.engine.workspace.agent_releases(self.project)


class AgentSessionTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.app.engine.simulated = False
        self.app.engine.directory = Path("/unused")
        self.project = Mock(name="project")
        self.project.name = "api"
        self.project.configuration.selected_agents = ["claude"]
        self.app.engine.agent_versions.return_value = {"claude": "1.0.0"}

    def test_update_offline_is_nonblocking_at_startup_but_explicit_update_fails(self):
        with (
            patch("brig.ui.sessions.releases", side_effect=BrigError("offline")),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(sessions.update_agents(self.app, self.project), "")
            with self.assertRaisesRegex(BrigError, "offline"):
                sessions.update_agents(self.app, self.project, force=True)

    def test_update_confirmation_decline_accept_and_no_input(self):
        with (
            patch("brig.ui.sessions.releases", return_value={"claude": "2.0.0"}),
            patch("brig.ui.sessions.interactive", return_value=True),
            redirect_stderr(io.StringIO()),
        ):
            with patch("builtins.input", return_value="n"):
                self.assertIn(
                    "Updates available", sessions.update_agents(self.app, self.project)
                )
            self.app.update_agents.assert_not_called()
            self.assertIn(
                "Updates available",
                sessions.update_agents(self.app, self.project, no_input=True),
            )
            with patch("builtins.input", return_value="s"):
                sessions.update_agents(self.app, self.project)
            self.app.update_agents.assert_called_with("api", {"claude": "2.0.0"})
            sessions.update_agents(self.app, self.project, yes=True)
        with patch("brig.ui.sessions.releases", return_value={"claude": "1.0.0"}):
            self.assertIn(
                "up to date", sessions.update_agents(self.app, self.project, force=True)
            )
            self.assertEqual(sessions.update_agents(self.app, self.project), "")
        self.app.engine.simulated = True
        self.assertIn("simulation", sessions.update_agents(self.app, self.project))

    def test_first_login_is_reused_and_missing_login_is_actionable_without_tty(self):
        self.app.engine.has_credentials.return_value = True
        sessions.ensure_login(self.app, self.project, "claude")
        self.app.authenticate_agent.assert_not_called()
        self.app.engine.has_credentials.return_value = False
        with self.assertRaisesRegex(BrigError, "brig auth login"):
            sessions.ensure_login(self.app, self.project, "claude", no_input=True)
        with (
            patch("brig.ui.sessions.interactive", return_value=True),
            patch("builtins.input", return_value="1"),
        ):
            self.app.engine.has_credentials.side_effect = [False, True]
            sessions.ensure_login(self.app, self.project, "claude")
        self.app.authenticate_agent.assert_called_with("api", "claude")
        with (
            patch("brig.ui.sessions.interactive", return_value=True),
            patch("builtins.input", return_value="1"),
        ):
            self.app.engine.has_credentials.side_effect = [False, False]
            with self.assertRaisesRegex(BrigError, "did not save"):
                sessions.ensure_login(self.app, self.project, "claude")

    def test_api_key_authentication_stays_in_host_and_invalid_choices_do_not_launch(
        self,
    ):
        with (
            patch("brig.ui.sessions.interactive", return_value=True),
            patch("brig.ui.sessions.getpass.getpass", return_value="fixture-secret"),
        ):
            for agent, answers, provider in (
                ("claude", ["2"], None),
                ("opencode", ["2", "google"], "google"),
            ):
                with patch("builtins.input", side_effect=answers):
                    self.app.engine.has_credentials.side_effect = [False, True]
                    sessions.ensure_login(self.app, self.project, agent)
                self.app.authenticate_agent.assert_called_with(
                    "api", agent, provider=provider, key="fixture-secret"
                )
            for answers, message in (
                (["3"], "method 1 or 2"),
                (["2", "bad"], "Unsupported"),
            ):
                self.app.engine.has_credentials.side_effect = [False]
                with (
                    patch("builtins.input", side_effect=answers),
                    self.assertRaisesRegex(BrigError, message),
                ):
                    sessions.ensure_login(self.app, self.project, "opencode")

    def test_pending_references_apply_once_before_retrying_entry(self):
        action = Mock(side_effect=[PendingReferences("pending"), "entered"])
        events = []
        self.app.apply_references.side_effect = lambda name: events.append("apply")
        with (
            patch("brig.ui.sessions.interactive", return_value=True),
            patch(
                "builtins.input",
                side_effect=lambda message: events.append(message) or "s",
            ),
        ):
            result = sessions.with_reference_prompt(self.app, self.project, action)
        self.assertEqual(result, "entered")
        self.assertEqual(action.call_count, 2)
        self.app.apply_references.assert_called_once_with("api")
        self.assertIn("closes all existing sessions", events[0])
        self.assertIn("api", events[0])
        self.assertEqual(events[1], "apply")

    def test_pending_references_do_not_prompt_without_terminal_or_with_no_input(self):
        for no_input, terminal in ((True, True), (False, False)):
            action = Mock(side_effect=PendingReferences("pending"))
            with (
                patch("brig.ui.sessions.interactive", return_value=terminal),
                patch("builtins.input") as prompt,
                self.assertRaisesRegex(PendingReferences, "pending"),
            ):
                sessions.with_reference_prompt(
                    self.app, self.project, action, no_input=no_input
                )
            prompt.assert_not_called()
            self.assertEqual(action.call_count, 1)
        self.app.apply_references.assert_not_called()

    def test_decline_default_eof_and_interrupt_keep_the_running_environment(self):
        for answer in ("n", "", EOFError(), KeyboardInterrupt()):
            action = Mock(side_effect=PendingReferences("pending"))
            expected = (
                KeyboardInterrupt
                if isinstance(answer, KeyboardInterrupt)
                else Cancelled
            )
            with (
                patch("brig.ui.sessions.interactive", return_value=True),
                patch(
                    "builtins.input",
                    side_effect=answer
                    if isinstance(answer, BaseException)
                    else lambda message, answer=answer: answer,
                ),
                self.assertRaises(expected),
            ):
                sessions.with_reference_prompt(self.app, self.project, action)
            self.assertEqual(action.call_count, 1)
        self.app.apply_references.assert_not_called()

    def test_apply_errors_and_ordinary_docker_errors_never_retry_or_launch(self):
        action = Mock(side_effect=PendingReferences("pending"))
        self.app.apply_references.side_effect = BrigError("apply failed")
        with (
            patch("brig.ui.sessions.interactive", return_value=True),
            patch("builtins.input", return_value="y") as prompt,
            self.assertRaisesRegex(BrigError, "apply failed"),
        ):
            sessions.with_reference_prompt(self.app, self.project, action)
        self.assertEqual(action.call_count, 1)
        prompt.assert_called_once()
        self.app.apply_references.reset_mock()
        action = Mock(side_effect=BrigError("Docker unavailable"))
        with (
            patch("builtins.input") as prompt,
            self.assertRaisesRegex(BrigError, "Docker unavailable"),
        ):
            sessions.with_reference_prompt(self.app, self.project, action)
        prompt.assert_not_called()
        self.app.apply_references.assert_not_called()

    def test_a_second_pending_error_after_apply_does_not_prompt_in_a_loop(self):
        action = Mock(side_effect=PendingReferences("pending again"))
        with (
            patch("brig.ui.sessions.interactive", return_value=True),
            patch("builtins.input", return_value="y") as prompt,
            self.assertRaisesRegex(PendingReferences, "pending again"),
        ):
            sessions.with_reference_prompt(self.app, self.project, action)
        self.assertEqual(action.call_count, 2)
        prompt.assert_called_once()
        self.app.apply_references.assert_called_once_with("api")

    def test_prelaunch_checks_can_be_disabled_and_precede_agent_execution(self):
        def invoke(name, agent, *, before_launch):
            before_launch(self.project)
            return "launched"

        self.app.run_agent.side_effect = invoke
        with (
            patch("brig.ui.sessions.update_agents", return_value="updated") as update,
            patch("brig.ui.sessions.ensure_login") as login,
            patch("brig.ui.sessions.interactive", return_value=True),
            patch.dict("os.environ", {}, clear=True),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                sessions.run_agent(self.app, self.project, "claude"), "launched"
            )
            update.assert_called_once()
            login.assert_called_with(self.app, self.project, "claude", no_input=False)
            update.reset_mock()
            sessions.run_agent(self.app, self.project, "claude", check_updates=False)
            sessions.run_agent(self.app, self.project, "claude", no_input=True)
            with patch.dict("os.environ", {"BRIG_NO_UPDATE_CHECK": "1"}):
                sessions.run_agent(self.app, self.project, "claude")
            update.assert_not_called()


class AgentCommandTests(unittest.TestCase):
    def setUp(self):
        self.case = test_docker_engine.DockerEngineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.project = self.case.project

    def test_run_default_and_short_agent_names_dispatch_to_agent_not_bash(self):
        self.project.configuration.agents = ["claude", "codex"]
        self.project.configuration.agent = "claude"
        with (
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch("brig.ui.cli.run_agent", return_value="") as run,
        ):
            for argv, agent in (
                (["run", "api"], "claude"),
                (["run", "codex", "--project", "api"], "codex"),
                (["run", "api", "--agent", "codex"], "codex"),
            ):
                self.assertEqual(main(argv), 0)
                self.assertEqual(run.call_args.args[2], agent)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["run", "codex", "--agent", "claude"]), 1)
        self.assertEqual(self.case.runner.calls, [])

    def test_legacy_agent_no_input_uses_default_without_picker(self):
        self.project.configuration.agents = ["claude", "codex"]
        with (
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch(
                "brig.ui.cli.choose_agent",
                side_effect=AssertionError("unexpected picker"),
            ),
            patch("brig.ui.cli.run_agent", return_value="") as run,
        ):
            self.assertEqual(main(["agent", "--project", "api", "--no-input"]), 0)
            self.assertEqual(run.call_args.args[2], "claude")

    def test_outside_project_uses_picker_but_explicit_errors_do_not(self):
        with (
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch("brig.ui.cli.Path.cwd", return_value=Path("/unregistered")),
            patch("brig.ui.cli.interactive", return_value=True),
            patch(
                "brig.ui.cli.curses.wrapper", side_effect=lambda pick: pick(object())
            ),
            patch(
                "brig.ui.tui.terminal.Terminal",
                return_value=ScriptedTerminal(choices=[0]),
            ),
            patch("brig.ui.cli.run_agent", return_value="") as run,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(["run", "claude"]), 0)
            run.assert_called_once()
            self.assertEqual(main(["run", "--no-input"]), 1)
            self.assertEqual(main(["run", "unknown"]), 1)
        with (
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch("brig.ui.cli.Path.cwd", return_value=Path("/unregistered")),
            patch("brig.ui.cli.interactive", return_value=True),
            patch("brig.ui.cli.curses.wrapper", side_effect=Cancelled),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(["run"]), 130)

    def test_bash_up_down_update_accept_positional_projects(self):
        with (
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch.object(self.case.app, "shell", return_value="") as shell,
            patch.object(self.case.app, "start", return_value="") as start,
            patch.object(self.case.app, "stop", return_value="") as stop,
            patch("brig.ui.cli.update_agents", return_value="") as update,
        ):
            for argv in (
                ["bash", "api"],
                ["up", "api"],
                ["down", "api"],
                ["update", "api", "--yes", "--no-input"],
            ):
                self.assertEqual(main(argv), 0)
            shell.assert_called_once()
            stop.assert_called_with("api")
            self.assertEqual(start.call_count, 2)
            self.assertTrue(update.call_args.kwargs["yes"])
