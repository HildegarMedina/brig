"""Real multi-agent executables and persistent storage, without live login."""

import os
import subprocess
import unittest

from brig.components.agents import AGENTS
from brig.docker.engine import DockerEngine
from brig.docker.isolation import agent_config, agent_uid
from brig.models import ProfileVersion
from brig.persistence.store import JsonStateStore
from tests.integration import test_lifecycle


@unittest.skipUnless(
    os.environ.get("BRIG_DOCKER_TESTS") == "1",
    "set BRIG_DOCKER_TESTS=1 to build agent images",
)
class AgentLifecycleTests(unittest.TestCase):
    setUp = test_lifecycle.DockerLifecycleTests.setUp
    inspect = test_lifecycle.DockerLifecycleTests.inspect

    def brig(self, *args, success=True, cwd=None, input_data=None):
        if args[0] in ("run", "shell"):
            args = (args[0], "--agent", self.active_agent, *args[1:])
        result = test_lifecycle.DockerLifecycleTests.brig(
            self, *args, success=False, cwd=cwd, input_data=input_data
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def remove_resources(self):
        test_lifecycle.DockerLifecycleTests.remove_resources(self)
        engine = DockerEngine(self.data / "runtime")

        for agent in ("codex", "opencode"):
            subprocess.run(
                ["docker", "volume", "rm", engine.agent_volume_name(agent)],
                capture_output=True,
                check=False,
            )

    def agent(self, project, agent, *command):
        return self.brig("agent", agent, "--project", project, "--command", *command)

    def test_work_container_has_agent_shared_login_and_project_history(self):
        shared_file = self.source / "host-code-test.txt"
        shared_file.write_text("host")
        shared_file.chmod(0o644)
        (self.source / "root-link").symlink_to("/usr/local/lib/brig/bootstrap.sh")
        for agent, integration in AGENTS.items():
            with self.subTest(agent=agent):
                self.active_agent = agent
                store = JsonStateStore(self.data)
                state = store.load()
                version = ProfileVersion(
                    len(state.profiles[0].versions) + 1,
                    {"python": os.environ.get("BRIG_TEST_PYTHON", "3.14.8")},
                    {},
                    {},
                    agent=agent,
                    agents=list(AGENTS),
                )
                state.profiles[0].versions.append(version)
                for project in state.projects:
                    project.configuration = version
                store.save(state)
                self.brig(
                    "auth",
                    "set-key",
                    agent,
                    "--project",
                    "integration-project",
                    "--stdin",
                    input_data="brig-fixture-not-a-real-key\n",
                )
                if agent == "claude":
                    # Simulate a former per-agent service. The next start must
                    # verify its ownership and retire it as a Compose orphan.
                    work = self.inspect("container", f"brig-{self.project_id}-dev")
                    subprocess.run(
                        [
                            "docker",
                            "run",
                            "--detach",
                            "--name",
                            f"brig-{self.project_id}-agent-codex",
                            "--label",
                            f"org.brig.project-id={self.project_id}",
                            "--label",
                            "org.brig.agent=codex",
                            "--label",
                            f"com.docker.compose.project=brig-{self.project_id}",
                            "--label",
                            "com.docker.compose.service=agent_codex",
                            "--label",
                            "com.docker.compose.config-hash=legacy-fixture",
                            "--label",
                            "com.docker.compose.oneoff=False",
                            work["Config"]["Image"],
                            "sleep",
                            "infinity",
                        ],
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                result = self.brig(
                    "run", "integration-project", "--command", agent, "--version"
                )
                self.assertTrue(result.stdout.strip())
                if agent == "claude":
                    # No recreation between these writes: a file created by
                    # one UID must be editable by the other selected agents.
                    for collaborator in AGENTS:
                        edit = (
                            "from pathlib import Path; "
                            "p=Path('shared-code-test.txt'); "
                            f"p.write_text((p.read_text() if p.exists() else '') + {collaborator!r}); "
                            "assert Path('host-code-test.txt').read_text().startswith('host'); "
                            f"Path('host-code-test.txt').write_text(Path('host-code-test.txt').read_text() + {collaborator!r})"
                        )
                        self.agent(
                            "integration-project", collaborator, "python", "-c", edit
                        )
                    self.assertEqual(
                        (self.source / "shared-code-test.txt").read_text(),
                        "".join(AGENTS),
                    )
                self.assertTrue(
                    self.agent(
                        "integration-project", agent, agent, "--version"
                    ).stdout.strip()
                )
                history_paths = [
                    f"{agent_config(agent)}/{name}"
                    for name in integration.history_directories
                ]
                program = (
                    "from pathlib import Path; import shutil; "
                    f"paths = {history_paths!r}; "
                    "[Path(path, 'brig-history-test').write_text('private') for path in paths]; "
                    "Path.home().joinpath('brig-settings-test').write_text('private'); "
                    "Path.home().joinpath('.local/state').mkdir(parents=True, exist_ok=True); "
                    "Path.home().joinpath('.local/state/brig-state-test').write_text('private'); "
                    f"assert all(shutil.which(name) is not None for name in {list(AGENTS)!r}); "
                    "assert not Path('/secrets').exists(); "
                    "assert not Path('/certificates').exists(); "
                    "assert not Path('/var/run/docker.sock').exists(); "
                    f"assert 'brig-fixture-not-a-real-key' not in Path('/opt/brig-auth/{agent}/auth.json').read_text(); "
                    f"assert 'brig-fixture-not-a-real-key' not in Path({agent_config(agent)!r}, {('.credentials.json' if agent == 'claude' else 'auth.json')!r}).read_text()"
                )
                network_check = (
                    "import os, socket; from pathlib import Path; "
                    f"assert os.getuid() == {agent_uid(agent, __import__('os').getuid())}; "
                    "status = Path('/proc/self/status').read_text(); "
                    "assert 'CapEff:\t0000000000000000' in status; "
                    "assert 'NoNewPrivs:\t1' in status; "
                    "assert not os.access('/usr/local/lib/brig/bootstrap.sh', os.W_OK); "
                    f"socket.create_connection(('credential_{agent}', 8080), 2).close(); "
                    f"others = {list(set(AGENTS) - {agent})!r}; "
                    "\nfor other in others:\n"
                    "    address = socket.gethostbyname('credential_' + other)\n"
                    "    try: socket.create_connection((address, 8080), 2)\n"
                    "    except OSError: pass\n"
                    "    else: raise AssertionError('other proxy is reachable')\n"
                    "    try: Path('/opt/brig-agent-home', other, '.brig-environment.sh').read_text()\n"
                    "    except PermissionError: pass\n"
                    "    else: raise AssertionError('other home is readable')\n"
                )
                self.brig(
                    "run",
                    "integration-project",
                    "--command",
                    "python",
                    "-c",
                    network_check,
                )
                self.brig(
                    "run", "integration-project", "--command", "python", "-c", program
                )
                other_program = (
                    "from pathlib import Path; "
                    f"assert all(not Path(path, 'brig-history-test').exists() for path in {history_paths!r}); "
                    "assert not Path.home().joinpath('brig-settings-test').exists(); "
                    "assert not Path.home().joinpath('.local/state/brig-state-test').exists(); "
                    f"assert Path('/opt/brig-auth/{agent}/auth.json').is_file()"
                )
                self.brig(
                    "run", "other-project", "--command", "python", "-c", other_program
                )
                shared = DockerEngine(self.data / "runtime").agent_volume_name(agent)
                for project_id in (self.project_id, self.other_id):
                    container = self.inspect("container", f"brig-{project_id}-dev")
                    self.assertEqual(container["State"]["Health"]["Status"], "healthy")
                    self.assertFalse(container["HostConfig"]["Privileged"])
                    self.assertNotIn(
                        shared, [mount.get("Name") for mount in container["Mounts"]]
                    )
                    public = next(
                        mount
                        for mount in container["Mounts"]
                        if mount["Destination"] == f"/opt/brig-auth/{agent}"
                    )
                    self.assertFalse(public["RW"])
                    proxy = self.inspect(
                        "container", f"brig-{project_id}-credential-{agent}"
                    )
                    self.assertIn(
                        shared, [mount.get("Name") for mount in proxy["Mounts"]]
                    )
                    self.assertEqual(proxy["State"]["Health"]["Status"], "healthy")
                    self.assertFalse(
                        any(
                            mount["Destination"] == "/workspace"
                            for mount in proxy["Mounts"]
                        )
                    )

                    resources = subprocess.run(
                        [
                            "docker",
                            "container",
                            "ls",
                            "--all",
                            "--filter",
                            f"label=org.brig.project-id={project_id}",
                            "--format",
                            "{{.Names}}",
                        ],
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                    self.assertEqual(
                        set(resources.stdout.split()),
                        {
                            f"brig-{project_id}-dev",
                            *[
                                f"brig-{project_id}-credential-{name}"
                                for name in AGENTS
                            ],
                        },
                    )
                self.brig("down", "--project", "integration-project")
                retained_program = (
                    "from pathlib import Path; "
                    f"assert all(Path(path, 'brig-history-test').read_text() == 'private' for path in {history_paths!r}); "
                    "assert Path.home().joinpath('brig-settings-test').read_text() == 'private'; "
                    "assert Path.home().joinpath('.local/state/brig-state-test').read_text() == 'private'"
                )
                self.agent(
                    "integration-project", agent, "python", "-c", retained_program
                )
                self.brig("down", "--project", "integration-project")
                self.brig("down", "--project", "other-project")
