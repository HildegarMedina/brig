"""Agent containers share project tools, never homes or provider credential mounts."""

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

    def test_each_agent_mounts_only_its_configuration_and_project_history(self):
        services = self.definition["services"]
        self.assertEqual(len(services["dev"]["volumes"]), 2)
        homes = set()
        for agent, integration in AGENTS.items():
            service = services[f"agent_{agent}"]
            self.assertEqual(
                service["container_name"], f"brig-{self.project.id}-agent-{agent}"
            )
            self.assertEqual(service["build"]["target"], f"agent_{agent}")
            self.assertEqual(service["image"], f"brig-test:tag-agent-{agent}")
            mounts = {item["target"]: item for item in service["volumes"]}
            self.assertEqual(mounts["/workspace"]["source"], self.project.path)
            home = mounts["/home/brig"]["source"]
            self.assertNotEqual(home, "home")
            homes.add(home)
            self.assertNotIn(integration.config_directory, mounts)
            self.assertTrue(mounts["/opt/brig-auth"]["read_only"])
            proxy = services[f"credential_{agent}"]
            self.assertEqual(proxy["volumes"][0]["source"], f"{agent}_config")
            for other, other_integration in AGENTS.items():
                if other != agent:
                    self.assertNotIn(other_integration.config_directory, mounts)
                    self.assertNotIn(
                        f"{other}_config",
                        [mount["source"] for mount in mounts.values()],
                    )
            for history in integration.history_directories:
                self.assertIn(f"{integration.config_directory}/{history}", mounts)
            self.assertEqual(service["env_file"], ["development.env"])
            self.assertEqual(
                {
                    name: value
                    for name, value in service["depends_on"].items()
                    if not name.startswith("credential_")
                },
                services["dev"]["depends_on"],
            )
            self.assertNotIn("privileged", service)
            self.assertNotIn("network_mode", service)
            self.assertNotIn("default", proxy["networks"])
        self.assertEqual(len(homes), len(AGENTS))

    def test_existing_login_and_history_volume_names_are_preserved(self):
        prefix = f"brig-{self.project.id}"
        volumes = self.definition["volumes"]
        for agent in AGENTS:
            self.assertEqual(volumes[f"{agent}_config"]["name"], f"brig-{agent}-1234")
            self.assertTrue(volumes[f"{agent}_config"]["external"])
            self.assertEqual(
                volumes[f"{agent}_history"]["name"], f"{prefix}-{agent}-history"
            )
            self.assertEqual(
                volumes[f"{agent}_home"]["name"], f"{prefix}-{agent}-runtime-home"
            )
        self.assertEqual(volumes["home"]["name"], f"{prefix}-home")

    def test_unselected_agents_have_no_service_image_or_mount(self):
        self.project.configuration.agents = ["claude"]
        definition = compose_definition(self.project, "brig-test", 1234, 4321)
        self.assertIn("agent_claude", definition["services"])
        for agent in ("codex", "opencode"):
            self.assertNotIn(f"agent_{agent}", definition["services"])
            self.assertNotIn(f"{agent}_config", definition["volumes"])
        self.assertNotIn("agent_codex", render_dockerfile(self.project))

    def test_agent_without_persistent_configuration_has_its_own_home(self):
        with patch.dict(
            AGENTS,
            claude=replace(
                AGENTS["claude"], config_directory=None, config_environment=None
            ),
        ):
            definition = compose_definition(self.project, "brig-test", 1234, 4321)
            contents = render_dockerfile(self.project)
        self.assertEqual(len(definition["services"]["agent_claude"]["volumes"]), 2)
        self.assertNotIn("None/projects", contents)

    def test_dockerfile_targets_inherit_tools_and_contain_one_agent(self):
        text = render_dockerfile(self.project)
        common = text.split("AS development\n", 1)[1].split(
            "FROM development AS agent_", 1
        )[0]
        self.assertNotIn("/opt/brig-codex", common)
        self.assertNotIn("/opt/brig-claude", common)
        self.assertNotIn("/opt/brig-opencode", common)
        self.assertIn("postgresql-client", common)
        self.assertIn("redis-tools", common)
        for agent in AGENTS:
            target = text.split(f"FROM development AS agent_{agent}\n", 1)[1].split(
                "FROM development AS", 1
            )[0]
            self.assertIn(f"/opt/brig-{agent}", target)
            self.assertIn("USER brig", target)
            for other in set(AGENTS) - {agent}:
                self.assertNotIn(f"/opt/brig-{other}", target)
        self.assertTrue(text.endswith("FROM development AS dev\n\n"))
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", text)
        self.assertIn("--dangerously-skip-permissions", text)
        self.assertIn('"*":"allow"', text)

    def test_compose_yaml_parses_with_targets_and_nested_mounts(self):
        rendered = render_compose(self.project, "brig-test:tag", 1234, 4321)
        self.assertEqual(yaml.safe_load(rendered.replace("$$", "$")), self.definition)

    def test_description_includes_agent_containers_and_separate_homes(self):
        environment = self.case.engine.describe(self.project)
        self.assertEqual(set(environment.agents), set(AGENTS))
        for agent in AGENTS:
            self.assertIn(
                f"brig-{self.project.id}-{agent}-runtime-home", environment.volumes
            )
            self.assertEqual(
                environment.agents[agent], f"brig-{self.project.id}-agent-{agent}"
            )

    def test_noninteractive_commands_execute_in_the_selected_agent_container(self):
        before = deepcopy(self.case.app.state)
        for agent in AGENTS:
            with redirect_stderr(io.StringIO()):
                self.case.app.run_agent("api", agent, ["python", "--version"])
            command = self.case.runner.calls[-1][0]
            self.assertNotIn("-it", command)
            self.assertEqual(
                command[-3:],
                [f"brig-{self.project.id}-agent-{agent}", "python", "--version"],
            )
        self.assertEqual(self.case.app.state.profiles, before.profiles)

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

    def test_missing_agent_container_does_not_fall_back_to_dev(self):
        with (
            patch.object(self.case.engine.client, "inspect", return_value=None),
            self.assertRaisesRegex(BrigError, "stopped"),
        ):
            self.case.engine.run_agent(self.project, "claude", ["claude", "--version"])
        self.assertFalse(any(args[1] == "exec" for args, _ in self.case.runner.calls))

    def test_missing_agent_image_triggers_build_even_if_dev_image_exists(self):
        self.case.runner.image = True
        runner = self.case.engine.client.runner

        def missing(args, **options):
            if args[1:3] == ["image", "inspect"] and args[-1].endswith("-agent-codex"):
                return CompletedProcess(args, 1, "", "No such image")
            return runner(args, **options)

        self.case.engine.client.runner = missing
        self.case.start()
        builds = [args for args, _ in self.case.runner.calls if "build" in args]
        self.assertEqual(len(builds), 1)
        self.assertEqual(
            builds[0][-5:],
            [
                "dev",
                "credential_claude",
                "agent_claude",
                "agent_codex",
                "agent_opencode",
            ],
        )

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
                        "codex",
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
                [f"brig-{self.project.id}-agent-codex", "python", "--version"],
            )
            self.assertEqual(
                main(["--data-dir", folder, "agent", "--project", "api", "--command"]),
                1,
            )
