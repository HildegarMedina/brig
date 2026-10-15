"""Protected proxy mounts, ownership, and host-only login/key entry points."""

import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
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
            # Java's HttpClient rejects "_" in proxy hostnames.
            self.assertEqual(
                proxy["networks"][private_network]["aliases"], [f"credential-{agent}"]
            )
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
                next(
                    m
                    for m in service["volumes"]
                    if m["target"] == f"/opt/brig-auth/{agent}"
                )["read_only"]
            )
            self.assertFalse(
                any("_ca" in mount["source"] for mount in service["volumes"])
            )
            self.assertNotIn("ports", proxy)
            self.assertEqual(proxy["cap_drop"], ["ALL"])
            self.assertNotIn("HTTP_PROXY", service.get("environment", {}))

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
                    self.assertEqual(command[-2:], ["login", "--device-auth"])
                    self.assertIn('cli_auth_credentials_store="file"', command)
                    self.assertIn(
                        "/opt/brig-codex/packages/standalone/current/bin/codex", command
                    )
                elif agent == "claude":
                    self.assertEqual(
                        command[-3:], ["/opt/brig-claude/claude", "auth", "login"]
                    )
                else:
                    self.assertIn(
                        "/opt/brig-opencode/opencode auth export >", command[-1]
                    )
                self.assertIn("--force-recreate", self.case.runner.calls[-1][0])

    def opencode_login_script(self):
        with (
            patch("brig.docker.engine.sys.stdin.isatty", return_value=True),
            patch("brig.docker.engine.sys.stdout.isatty", return_value=True),
            redirect_stderr(io.StringIO()),
        ):
            self.case.app.authenticate_agent("api", "opencode")
        native = next(
            args
            for args, _ in reversed(self.case.runner.calls)
            if args[1] == "run" and "-it" in args
        )
        return native[-1]

    def test_opencode_native_provider_picker_works_for_legacy_and_exporting_clis(self):
        script = self.opencode_login_script()
        for mode, login_status, export_status in (
            ("legacy", 0, 0),
            ("v2", 0, 0),
            ("v2", 7, 0),
            ("v2", 0, 8),
        ):
            with (
                self.subTest(
                    mode=mode, login_status=login_status, export_status=export_status
                ),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                binary = root / "opencode fixture"
                log = root / "calls"
                export = root / "brig-export.json"
                original = '[{"integrationID":"openai","active":true,"value":{"type":"api","key":"previous-fixture"}}]'
                export.write_text(original)
                binary.write_text(
                    '#!/bin/sh\nset -eu\nif [ "$*" = "auth --help" ]; then\n    if [ "$TEST_MODE" = v2 ]; then printf \'  import   Import credentials\\n  export   Export credentials\\n\'; fi\n    exit 0\nfi\nprintf \'%s\\n\' "$*" >> "$TEST_CALLS"\ncase "$1 $2" in\n    \'auth login\')\n        # A positional provider would be interpreted as a URL by legacy CLIs.\n        test "$#" -eq 2 || exit 64\n        exit "$TEST_LOGIN_STATUS"\n        ;;\n    \'auth import\') cat > "$TEST_IMPORT" ;;\n    \'auth export\')\n        printf \'%s\' \'[{"integrationID":"opencode-go","active":true,"value":{"type":"api","key":"go-fixture"}}]\'\n        exit "$TEST_EXPORT_STATUS"\n        ;;\n    *) exit 99 ;;\nesac\n'
                )
                binary.chmod(0o755)
                translated = script.replace(
                    "/opt/brig-opencode/opencode", shlex.quote(str(binary))
                ).replace("/home/brig/.local/share/opencode", shlex.quote(str(root)))
                result = subprocess.run(
                    ["sh", "-ec", translated],
                    capture_output=True,
                    text=True,
                    env={
                        **os.environ,
                        "TEST_MODE": mode,
                        "TEST_LOGIN_STATUS": str(login_status),
                        "TEST_EXPORT_STATUS": str(export_status),
                        "TEST_CALLS": str(log),
                        "TEST_IMPORT": str(root / "imported"),
                    },
                    check=False,
                )
                calls = log.read_text().splitlines()
                self.assertIn("auth login", calls)
                self.assertNotIn("auth login openai", calls)
                self.assertNotIn("go-fixture", result.stdout + result.stderr)
                self.assertFalse((root / ".brig-export.tmp").exists())
                if mode == "legacy":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(calls, ["auth login"])
                    self.assertEqual(export.read_text(), original)
                elif login_status or export_status:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(export.read_text(), original)
                    if login_status:
                        self.assertNotIn("auth export", calls)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("auth export", calls)
                    self.assertEqual(
                        json.loads(export.read_text())[0]["integrationID"],
                        "opencode-go",
                    )
                    self.assertEqual(export.stat().st_mode & 0o777, 0o600)
                    self.assertEqual((root / "imported").read_text(), original)

    def test_failed_opencode_login_does_not_clear_overrides_or_restart(self):
        self.case.start()
        self.case.runner.calls.clear()
        original_runner = self.case.runner

        def runner(args, **options):
            result = original_runner(args, **options)
            if args[1] == "run" and "-it" in args:
                return CompletedProcess(args, 7)
            return result

        with (
            patch.object(self.case.engine.client, "runner", side_effect=runner),
            self.assertRaises(BrigError),
        ):
            self.case.engine.authenticate_agent(self.project, "opencode")
        commands = [args for args, _ in self.case.runner.calls]
        self.assertTrue(any("snapshot_login" in args[-1] for args in commands))
        self.assertFalse(any("clear_override" in args[-1] for args in commands))
        self.assertFalse(any("--force-recreate" in args for args in commands))

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

    def test_cli_accepts_opencode_go_key_without_an_openai_login(self):
        self.project.configuration.agent = "opencode"
        with (
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch("sys.stdin", io.StringIO(self.key + "\n")),
            patch("sys.stdout", new_callable=io.StringIO) as output,
            redirect_stderr(io.StringIO()),
        ):
            result = main(
                [
                    "auth",
                    "set-key",
                    "opencode",
                    "--project",
                    "api",
                    "--provider",
                    "opencode-go",
                    "--stdin",
                ]
            )
        self.assertEqual(result, 0)
        command, options = next(
            (args, options)
            for args, options in self.case.runner.calls
            if "set_api_key" in args[-1]
        )
        self.assertEqual(
            json.loads(options["input"]), {"provider": "opencode-go", "key": self.key}
        )
        self.assertNotIn(self.key, " ".join(command))
        self.assertNotIn(self.key, output.getvalue())

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
