"""One project work container keeps history private and credentials in its proxy."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from copy import deepcopy
from dataclasses import replace
from subprocess import CompletedProcess
from unittest.mock import patch

import yaml

from brig.components.agents import AGENTS
from brig.docker.compose import compose_definition, render_compose
from brig.docker.dockerfile import render_dockerfile
from brig.errors import BrigError
from brig.ui.cli import main
from tests import test_docker_engine


class AgentIsolationTests(unittest.TestCase):
    def setUp(self):
        self.case = test_docker_engine.DockerEngineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.project = self.case.project
        self.project.configuration.agents = list(AGENTS)
        self.definition = compose_definition(self.project, "brig-test:tag", 1234, 4321)

    def test_one_work_container_has_only_the_active_agent_proxy_and_history(self):
        for agent, integration in AGENTS.items():
            self.project.configuration.agent = agent
            definition = compose_definition(self.project, "brig-test:tag", 1234, 4321)
            services = definition["services"]
            self.assertEqual(
                set(services), {"dev", f"credential_{agent}", "postgresql", "redis"}
            )
            service = services["dev"]
            self.assertEqual(service["build"]["target"], "dev")
            self.assertEqual(service["image"], "brig-test:tag")
            mounts = {item["target"]: item for item in service["volumes"]}
            self.assertEqual(mounts["/workspace"]["source"], self.project.path)
            self.assertEqual(mounts["/home/brig"]["source"], "home")
            self.assertNotIn(integration.config_directory, mounts)
            self.assertTrue(mounts["/opt/brig-auth"]["read_only"])
            self.assertNotIn(f"{agent}_config", [m["source"] for m in mounts.values()])
            proxy = services[f"credential_{agent}"]
            self.assertEqual(proxy["volumes"][0]["source"], f"{agent}_config")
            self.assertNotIn("default", proxy["networks"])
            for history in integration.history_directories:
                self.assertIn(f"{integration.config_directory}/{history}", mounts)
            self.assertEqual(service["env_file"], ["development.env"])
            self.assertEqual(
                service["depends_on"]["redis"], {"condition": "service_healthy"}
            )
            self.assertNotIn("privileged", service)
            self.assertFalse(
                any(m["target"] == "/var/run/docker.sock" for m in mounts.values())
            )

    def test_existing_login_home_and_history_volume_names_are_preserved(self):
        prefix = f"brig-{self.project.id}"
        for agent in AGENTS:
            self.project.configuration.agent = agent
            volumes = compose_definition(self.project, "brig-test", 1234, 4321)[
                "volumes"
            ]
            self.assertEqual(volumes[f"{agent}_config"]["name"], f"brig-{agent}-1234")
            self.assertTrue(volumes[f"{agent}_config"]["external"])
            self.assertEqual(
                volumes[f"{agent}_history"]["name"], f"{prefix}-{agent}-history"
            )
            self.assertEqual(volumes["home"]["name"], f"{prefix}-{agent}-runtime-home")

    def test_inactive_agents_have_no_image_proxy_or_credential_mount(self):
        definition = self.definition
        text = render_dockerfile(self.project)
        for agent in ("codex", "opencode"):
            self.assertNotIn(f"credential_{agent}", definition["services"])
            self.assertNotIn(f"{agent}_config", definition["volumes"])
            self.assertNotIn(f"AS {agent}_binary", text)

    def test_agent_without_persistent_configuration_has_project_home(self):
        with patch.dict(
            AGENTS,
            claude=replace(
                AGENTS["claude"], config_directory=None, config_environment=None
            ),
        ):
            definition = compose_definition(self.project, "brig-test", 1234, 4321)
            contents = render_dockerfile(self.project)
        self.assertEqual(len(definition["services"]["dev"]["volumes"]), 2)
        self.assertNotIn("None/projects", contents)

    def test_work_image_contains_tools_and_only_default_agent(self):
        for agent in AGENTS:
            self.project.configuration.agent = agent
            text = render_dockerfile(self.project)
            self.assertIn("postgresql-client", text)
            self.assertIn("redis-tools", text)
            self.assertIn("FROM development AS dev", text)
            self.assertIn(f"/opt/brig-{agent}", text)
            self.assertTrue(text.endswith("USER brig\n\n"))
            for other in set(AGENTS) - {agent}:
                self.assertNotIn(f"/opt/brig-{other}", text)

    def test_compose_yaml_parses_with_targets_and_nested_mounts(self):
        rendered = render_compose(self.project, "brig-test:tag", 1234, 4321)
        self.assertEqual(yaml.safe_load(rendered.replace("$$", "$")), self.definition)

    def test_description_lists_same_container_for_shell_and_active_agent(self):
        environment = self.case.engine.describe(self.project)
        self.assertEqual(environment.agents, {"claude": environment.development})
        self.assertIn(
            f"brig-{self.project.id}-claude-runtime-home", environment.volumes
        )
        self.assertNotIn(f"brig-{self.project.id}-home", environment.volumes)

    def test_shell_and_agent_execute_in_the_same_container(self):
        before = deepcopy(self.case.app.state.profiles)
        with redirect_stderr(io.StringIO()):
            self.case.app.run_agent("api", "claude", ["python", "--version"])
            agent_command = self.case.runner.calls[-1][0]
            self.case.app.shell("api", ["python", "--version"])
            shell_command = self.case.runner.calls[-1][0]
        self.assertEqual(agent_command, shell_command)
        self.assertNotIn("-it", agent_command)
        self.assertEqual(
            agent_command[-3:], [f"brig-{self.project.id}-dev", "python", "--version"]
        )
        self.assertEqual(self.case.app.state.profiles, before)

    def test_selected_nondefault_agent_is_rejected_before_docker(self):
        for action in (
            lambda: self.case.app.run_agent("api", "codex", ["codex", "--version"]),
            lambda: self.case.app.authenticate_agent("api", "codex", key="fixture-key"),
            lambda: self.case.engine.run_agent(
                self.project, "codex", ["codex", "--version"]
            ),
            lambda: self.case.engine.authenticate_agent(
                self.project, "codex", key="fixture-key"
            ),
        ):
            with self.assertRaisesRegex(BrigError, "default agent"):
                action()
        self.assertEqual(self.case.runner.calls, [])

    def test_existing_agent_with_wrong_role_is_rejected_before_start(self):
        self.case.runner.exists = True

        def foreign(args, **options):
            if args[1:3] == ["container", "inspect"] and "-agent-" in args[-1]:
                return CompletedProcess(
                    args,
                    0,
                    json.dumps(
                        [
                            {
                                "Config": {
                                    "Labels": {
                                        "org.brig.project-id": self.project.id,
                                        "org.brig.agent": "wrong",
                                    }
                                },
                                "State": {"Running": True},
                            }
                        ]
                    ),
                    "",
                )
            return self.case.runner(args, **options)

        self.case.engine.client.runner = foreign
        with self.assertRaisesRegex(BrigError, "not managed"):
            self.case.start()
        self.assertFalse(any("up" in args for args, _ in self.case.runner.calls))

    def test_missing_work_container_prevents_agent_execution(self):
        with (
            patch.object(self.case.engine.client, "inspect", return_value=None),
            self.assertRaisesRegex(BrigError, "stopped"),
        ):
            self.case.engine.run_agent(self.project, "claude", ["claude", "--version"])
        self.assertFalse(any(args[1] == "exec" for args, _ in self.case.runner.calls))

    def test_missing_proxy_image_triggers_build_even_if_work_image_exists(self):
        self.case.runner.image = True
        runner = self.case.engine.client.runner

        def missing(args, **options):
            if args[1:3] == ["image", "inspect"] and args[-1].endswith(
                "-credential-proxy"
            ):
                return CompletedProcess(args, 1, "", "No such image")
            return runner(args, **options)

        self.case.engine.client.runner = missing
        self.case.start()
        builds = [args for args, _ in self.case.runner.calls if "build" in args]
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0][-2:], ["dev", "credential_claude"])

    def test_cli_agent_command_and_empty_command(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("brig.ui.cli.Application", return_value=self.case.app),
            patch("brig.ui.cli.DockerEngine"),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                main(
                    [
                        "--data-dir",
                        folder,
                        "agent",
                        "claude",
                        "--project",
                        "api",
                        "--command",
                        "python",
                        "--version",
                    ]
                ),
                0,
            )
            self.assertEqual(
                self.case.runner.calls[-1][0][-3:],
                [f"brig-{self.project.id}-dev", "python", "--version"],
            )
            self.assertEqual(
                main(["--data-dir", folder, "agent", "--project", "api", "--command"]),
                1,
            )
