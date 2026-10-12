"""Protected proxy mounts, ownership, and host-only login/key entry points."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from subprocess import CompletedProcess
from unittest.mock import patch

from brig.errors import BrigError
from brig.ui.cli import main
from tests import test_docker_engine


class AuthDockerTests(unittest.TestCase):
    def setUp(self):
        self.case = test_docker_engine.DockerEngineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.project = self.case.project
        self.project.configuration.agents = ["claude", "codex", "opencode"]
        self.key = "fixture-secret-input-not-an-argument"

    def test_each_proxy_is_private_and_agents_receive_only_public_view(self):
        from brig.docker.compose import compose_definition

        for agent in self.project.configuration.selected_agents:
            self.project.configuration.agent = agent
            definition = compose_definition(self.project, "brig-test", 1234, 4321)
            service = definition["services"]["dev"]
            proxy = definition["services"][f"credential_{agent}"]
            self.assertNotIn("default", proxy["networks"])
            self.assertNotIn("credential_egress", service["networks"])
            private_network = f"credential_{agent}"
            self.assertTrue(definition["networks"][private_network]["internal"])
            self.assertEqual(
                set(proxy["networks"]) & set(service["networks"]), {private_network}
            )
            self.assertFalse(
                any(
                    mount["source"] == f"{agent}_config" for mount in service["volumes"]
                )
            )
            self.assertEqual(proxy["volumes"][0]["source"], f"{agent}_config")
            self.assertFalse(
                any(mount["target"] == "/workspace" for mount in proxy["volumes"])
            )
            self.assertTrue(
                next(m for m in service["volumes"] if m["target"] == "/opt/brig-auth")[
                    "read_only"
                ]
            )
            self.assertFalse(
                any("_ca" in mount["source"] for mount in service["volumes"])
            )
            self.assertNotIn("ports", proxy)
            self.assertEqual(proxy["cap_drop"], ["ALL"])
            self.assertEqual(
                service["environment"]["HTTP_PROXY"], f"http://credential_{agent}:8080"
            )

    def test_native_login_helpers_never_mount_workspace_or_public_proxy_view(self):
        with (
            patch("brig.docker.engine.sys.stdin.isatty", return_value=True),
            patch("brig.docker.engine.sys.stdout.isatty", return_value=True),
            redirect_stderr(io.StringIO()),
        ):
            for agent in self.project.configuration.selected_agents:
                self.case.app.project("api").configuration.agent = agent
                self.case.app.authenticate_agent("api", agent)
                command = next(
                    args
                    for args, _ in reversed(self.case.runner.calls)
                    if args[1] == "run" and "-it" in args
                )
                self.assertNotIn(self.project.path, " ".join(command))
                self.assertNotIn("/workspace", " ".join(command))
                self.assertNotIn("/opt/brig-auth", " ".join(command))
                self.assertIn("-it", command)
                if agent == "codex":
                    self.assertEqual(command[-3:], ["codex", "login", "--device-auth"])
                elif agent == "claude":
                    self.assertEqual(command[-3:], ["claude", "auth", "login"])
                else:
                    self.assertIn("opencode auth export >", command[-1])
                self.assertIn("--force-recreate", self.case.runner.calls[-1][0])

    def test_keys_use_stdin_not_arguments_and_helpers_have_no_network(self):
        self.project.configuration.agent = "codex"
        with redirect_stderr(io.StringIO()):
            message = self.case.app.authenticate_agent("api", "codex", key=self.key)
        self.assertIn("Authentication saved", message)
        command, options = next(
            (args, options)
            for args, options in reversed(self.case.runner.calls)
            if args[1] == "run"
        )
        self.assertNotIn(self.key, " ".join(command))
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertEqual(
            json.loads(options["input"]), {"provider": "openai", "key": self.key}
        )
        self.assertTrue(options["capture_output"])
        self.assertNotIn(self.key, message)

    def test_authentication_validation_precedes_docker_operations(self):
        self.project.configuration.agent = "codex"
        for agent, options in (
            ("unknown", {}),
            ("codex", {"key": self.key, "provider": "anthropic"}),
            ("codex", {"key": "short"}),
            ("codex", {"key": "line\nbreak-key"}),
            ("codex", {"key": "ü" * 12}),
            ("codex", {"key": []}),
        ):
            with self.assertRaises(BrigError):
                self.case.app.authenticate_agent("api", agent, **options)
        self.project.configuration.agents = ["claude"]
        self.project.configuration.agent = "claude"
        with self.assertRaisesRegex(BrigError, "not selected"):
            self.case.app.authenticate_agent("api", "codex")
        self.assertEqual(self.case.runner.calls, [])
        with (
            patch("brig.docker.engine.sys.stdin.isatty", return_value=False),
            self.assertRaisesRegex(BrigError, "interactive terminal"),
        ):
            self.case.app.authenticate_agent("api", "claude")

    def test_login_failures_do_not_echo_secret_stderr_or_restart_containers(self):
        self.project.configuration.agent = "codex"
        self.case.start()
        for exception in (None, OSError(self.key)):

            def failure(args, *, fixture_error=exception, **options):
                if args[1] == "run":
                    if fixture_error:
                        raise fixture_error
                    return CompletedProcess(args, 1, self.key, self.key)
                return self.case.runner(args, **options)

            with (
                patch.object(self.case.engine.client, "runner", side_effect=failure),
                self.assertRaises(BrigError) as error,
            ):
                self.case.engine.authenticate_agent(
                    self.project, "codex", provider="openai", key=self.key
                )
            self.assertNotIn(self.key, str(error.exception))

    def test_cli_hidden_key_prompt_and_login_use_host_authentication(self):
        self.project.configuration.agent = "opencode"
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch("brig.ui.cli.DockerEngine"),
            patch("brig.ui.cli.getpass.getpass", return_value=self.key),
            patch.object(self.case.engine, "validate_shell"),
            patch("brig.docker.engine.sys.stdin.isatty", return_value=True),
            patch("brig.docker.engine.sys.stdout.isatty", return_value=True),
            patch("sys.stdout", new_callable=io.StringIO) as output,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                main(
                    [
                        "--data-dir",
                        folder,
                        "auth",
                        "set-key",
                        "opencode",
                        "--provider",
                        "google",
                        "--project",
                        "api",
                    ]
                ),
                0,
            )
            self.case.app.project("api").configuration.agent = "claude"
            self.assertEqual(
                main(
                    [
                        "--data-dir",
                        folder,
                        "auth",
                        "login",
                        "claude",
                        "--project",
                        "api",
                    ]
                ),
                0,
            )
            self.assertNotIn(self.key, output.getvalue())

    def test_stdin_key_entry_is_noninteractive_and_does_not_echo(self):
        self.project.configuration.agent = "codex"
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch("brig.ui.cli.DockerEngine"),
            patch("sys.stdin", io.StringIO(self.key + "\n")),
            patch("sys.stdout", new_callable=io.StringIO) as output,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                main(
                    [
                        "--data-dir",
                        folder,
                        "auth",
                        "set-key",
                        "codex",
                        "--stdin",
                        "--project",
                        "api",
                    ]
                ),
                0,
            )
            self.assertNotIn(self.key, output.getvalue())

    def test_proxy_ownership_conflict_stops_startup(self):
        from brig.docker.client import DockerClient

        project = self.project
        result = CompletedProcess(
            [],
            0,
            json.dumps(
                [
                    {
                        "Config": {
                            "Labels": {
                                "org.brig.project-id": project.id,
                                "org.brig.auth-proxy": "wrong",
                            }
                        }
                    }
                ]
            ),
            "",
        )
        client = DockerClient(lambda *args, **kwargs: result)
        client._checked = True
        with self.assertRaisesRegex(BrigError, "not managed"):
            client.inspect(project, agent="codex", proxy=True)
