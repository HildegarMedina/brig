"""One project work container keeps history private and credentials in its proxy."""

import io
import json
import shlex
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import yaml

from brig.components.agents import AGENTS, INSTRUCTIONS_FILE
from brig.docker.compose import compose_definition, render_compose
from brig.docker.dockerfile import render_dockerfile
from brig.docker.isolation import (
    agent_config,
    agent_home,
    agent_uid,
    bootstrap_script,
)
from brig.docker.services import SERVICE_HINTS, SERVICES, agent_instructions
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

    def test_one_work_container_has_all_selected_agents_with_private_homes(self):
        for agent, integration in AGENTS.items():
            self.project.configuration.agent = agent
            definition = compose_definition(self.project, "brig-test:tag", 1234, 4321)
            services = definition["services"]
            self.assertEqual(
                set(services),
                {
                    "dev",
                    "postgresql",
                    "redis",
                    *[f"credential_{name}" for name in AGENTS],
                },
            )
            service = services["dev"]
            self.assertEqual(service["build"]["target"], "dev")
            self.assertEqual(service["image"], "brig-test:tag")
            mounts = {item["target"]: item for item in service["volumes"]}
            self.assertEqual(mounts["/workspace"]["source"], self.project.path)
            self.assertEqual(mounts["/home/brig"]["source"], "home")
            self.assertNotIn(integration.config_directory, mounts)
            self.assertTrue(mounts[f"/opt/brig-auth/{agent}"]["read_only"])
            self.assertNotIn(f"{agent}_config", [m["source"] for m in mounts.values()])
            proxy = services[f"credential_{agent}"]
            self.assertEqual(proxy["volumes"][0]["source"], f"{agent}_config")
            self.assertNotIn("default", proxy["networks"])
            for history in integration.history_directories:
                self.assertIn(f"{agent_config(agent)}/{history}", mounts)
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
            self.assertEqual(
                volumes[f"{agent}_home"]["name"], f"{prefix}-{agent}-runtime-home"
            )

    def test_inactive_agents_have_no_image_proxy_or_credential_mount(self):
        self.project.configuration.agents = ["claude"]
        definition = compose_definition(self.project, "brig-test", 1234, 4321)
        text = render_dockerfile(self.project)
        for agent in ("codex", "opencode"):
            self.assertNotIn(f"credential_{agent}", definition["services"])
            self.assertNotIn(f"{agent}_config", definition["volumes"])
            self.assertNotIn(f"AS {agent}_binary", text)

    def test_agent_without_persistent_configuration_has_project_home(self):
        self.project.configuration.agents = ["claude"]
        with patch.dict(
            AGENTS,
            claude=replace(
                AGENTS["claude"], config_directory=None, config_environment=None
            ),
        ):
            definition = compose_definition(self.project, "brig-test", 1234, 4321)
            contents = render_dockerfile(self.project)
        self.assertEqual(len(definition["services"]["dev"]["volumes"]), 3)
        self.assertNotIn("None/projects", contents)

    @unittest.skipUnless(shutil.which("jq"), "jq is required")
    def test_claude_onboarding_is_completed_as_the_agent(self):
        line = next(
            line
            for line in bootstrap_script(["claude", "codex"]).splitlines()
            if "hasCompletedOnboarding" in line
        )
        self.assertTrue(line.startswith('setpriv --reuid "$actor_uid"'))
        script = shlex.split(line.removesuffix(" || true"))[-1]
        with tempfile.TemporaryDirectory() as folder:
            script = script.replace(agent_config("claude"), folder)
            path = Path(folder) / ".claude.json"
            subprocess.run(["sh", "-c", script], check=True)
            self.assertEqual(
                json.loads(path.read_text()), {"hasCompletedOnboarding": True}
            )
            path.write_text('{"theme": "dark", "hasCompletedOnboarding": false}')
            subprocess.run(["sh", "-c", script], check=True)
            self.assertEqual(
                json.loads(path.read_text()),
                {"theme": "dark", "hasCompletedOnboarding": True},
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_work_image_contains_tools_and_every_selected_agent(self):
        for agent in AGENTS:
            self.project.configuration.agent = agent
            text = render_dockerfile(self.project)
            self.assertIn("postgresql-client", text)
            self.assertIn("redis-tools", text)
            self.assertIn("FROM development AS dev", text)
            self.assertIn(f"/opt/brig-{agent}", text)
            self.assertIn('ENTRYPOINT ["/usr/local/lib/brig/bootstrap.sh"]', text)
            for other in AGENTS:
                self.assertIn(f"/opt/brig-{other}", text)
                self.assertIn(f"brig-agent-{other}", text)

    def test_compose_yaml_parses_with_targets_and_nested_mounts(self):
        rendered = render_compose(self.project, "brig-test:tag", 1234, 4321)
        self.assertEqual(yaml.safe_load(rendered.replace("$$", "$")), self.definition)

    def test_description_lists_same_container_for_shell_and_active_agent(self):
        environment = self.case.engine.describe(self.project)
        self.assertEqual(
            environment.agents, {agent: environment.development for agent in AGENTS}
        )
        self.assertIn(
            f"brig-{self.project.id}-claude-runtime-home", environment.volumes
        )
        self.assertNotIn(f"brig-{self.project.id}-home", environment.volumes)

    def test_shell_and_agent_execute_in_the_same_container(self):
        before = deepcopy(self.case.app.state.profiles)
        with redirect_stderr(io.StringIO()):
            self.case.app.run_agent("api", "claude", ["python", "--version"])
            agent_command = self.case.runner.calls[-1][0]
            self.case.app.shell("api", ["python", "--version"], agent="claude")
            shell_command = self.case.runner.calls[-1][0]
        self.assertEqual(agent_command, shell_command)
        self.assertNotIn("-it", agent_command)
        self.assertEqual(agent_command[-2:], ["python", "--version"])
        self.assertEqual(self.case.app.state.profiles, before)

    def test_all_selected_agents_execute_with_distinct_users_and_proxy_environments(
        self,
    ):
        users = set()
        for agent in AGENTS:
            with redirect_stderr(io.StringIO()):
                self.case.app.run_agent("api", agent, ["python", "--version"])
            command = self.case.runner.calls[-1][0]
            user = command[command.index("--user") + 1]
            users.add(user)
            self.assertEqual(user, f"{agent_uid(agent, 1234)}:4321")
            self.assertIn(f"HTTPS_PROXY=http://credential_{agent}:8080", command)
            self.assertIn(f"HOME={agent_home(agent)}", command)
        self.assertEqual(len(users), 3)

    def test_ambiguous_shell_is_rejected_before_start(self):
        with self.assertRaisesRegex(BrigError, "Choose an agent"):
            self.case.app.shell("api", ["python", "--version"])
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
                self.case.runner.calls[-1][0][-2:],
                ["python", "--version"],
            )
            self.assertEqual(
                main(["--data-dir", folder, "agent", "--project", "api", "--command"]),
                1,
            )


class AgentInstructionsTests(unittest.TestCase):
    def test_instructions_state_the_sandbox_and_real_service_settings(self):
        text = agent_instructions({"postgresql": "17", "redis": "7"})
        self.assertIn("Brig sandbox", text)
        self.assertIn("NOT the databases, Redis", text)
        self.assertIn("take precedence over", text)
        self.assertIn("CLAUDE.md", text)
        self.assertIn("PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD", text)
        self.assertIn("REDIS_URL", text)
        self.assertNotIn("MYSQL_HOST", text)
        self.assertNotIn("No databases", text)

    def test_instructions_without_services_say_none_are_reachable(self):
        text = agent_instructions({})
        self.assertIn("Brig sandbox", text)
        self.assertIn("No databases or caches are provided here.", text)
        self.assertNotIn("PGHOST", text)

    def test_every_service_has_a_hint(self):
        self.assertEqual(set(SERVICE_HINTS), set(SERVICES))

    def test_bootstrap_writes_private_instructions_for_each_agent(self):
        services = {"postgresql": "17"}
        script = bootstrap_script(["claude", "codex"], services)
        for agent in ("claude", "codex"):
            path = f"{agent_home(agent)}/{INSTRUCTIONS_FILE}"
            line = f"printf '%s' {shlex.quote(agent_instructions(services))} > {path}"
            self.assertIn(line, script)
            self.assertIn(f"chmod 600 {path}", script)
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / INSTRUCTIONS_FILE
                subprocess.run(
                    ["sh", "-c", line.replace(path, str(target))], check=True
                )
                self.assertEqual(target.read_text(), agent_instructions(services))

    def test_dockerfile_bootstrap_uses_project_services(self):
        case = test_docker_engine.DockerEngineTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.assertIn("PGPASSWORD", render_dockerfile(case.project))

    def test_claude_wrapper_appends_instructions_to_the_system_prompt(self):
        line = next(
            line
            for line in AGENTS["claude"].image
            if line.startswith("RUN printf") and "/usr/local/bin/claude" in line
        )
        lines = shlex.split(line.removeprefix("RUN printf ").split(" > ")[0])[1:]
        prepare = [
            entry
            for entry in lines
            if "instructions" in entry
            and INSTRUCTIONS_FILE in entry
            or "append-system-prompt" in entry
        ]
        self.assertEqual(len(prepare), 2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / INSTRUCTIONS_FILE
            script = "\n".join(
                [
                    *(
                        entry.replace(
                            f"/opt/brig-agent-home/claude/{INSTRUCTIONS_FILE}",
                            str(path),
                        )
                        for entry in prepare
                    ),
                    "printf '%s\\n' \"$@\"",
                ]
            )

            def run():
                return subprocess.run(
                    ["sh", "-ec", script, "wrapper", "--resume"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout

            self.assertEqual(run(), "--resume\n")
            path.write_text("line one\nline 'two'")
            self.assertEqual(
                run(),
                "--append-system-prompt\nline one\nline 'two'\n--resume\n",
            )
