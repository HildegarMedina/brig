"""Real multi-agent executables and persistent storage, without live login."""

import os
import unittest

from brig.docker.engine import DockerEngine
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

    def brig(self, *args, success=True, cwd=None):
        result = test_lifecycle.DockerLifecycleTests.brig(
            self, *args, success=False, cwd=cwd
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def remove_resources(self):
        test_lifecycle.DockerLifecycleTests.remove_resources(self)
        engine = DockerEngine(self.data / "runtime")
        import subprocess

        for agent in ("codex", "opencode"):
            subprocess.run(
                ["docker", "volume", "rm", engine.agent_volume_name(agent)],
                capture_output=True,
                check=False,
            )

    def agent(self, project, agent, *command):
        return self.brig("agent", agent, "--project", project, "--command", *command)

    def test_native_agents_share_credentials_and_keep_project_state(self):
        store = JsonStateStore(self.data)
        state = store.load()
        version = ProfileVersion(
            2,
            {"python": os.environ.get("BRIG_TEST_PYTHON", "3.14.8")},
            {},
            {},
            agent="codex",
            agents=["claude", "codex", "opencode"],
        )
        state.profiles[0].versions.append(version)
        for project in state.projects:
            project.configuration = version
        store.save(state)
        for agent in version.selected_agents:
            result = self.agent("integration-project", agent, agent, "--version")
            self.assertTrue(result.stdout.strip())
        self.agent(
            "integration-project",
            "codex",
            "sh",
            "-ec",
            """
            umask 077
            printf '{"OPENAI_API_KEY":"brig-fixture-not-a-real-key"}' > "$CODEX_HOME/auth.json"
            printf private > "$CODEX_HOME/sessions/brig-test"
            printf private > "$CODEX_HOME/archived_sessions/brig-test"
            mkdir -p /home/brig/.local/state/codex
            printf private > /home/brig/.local/state/codex/brig-test
            test ! -e /home/brig/.local/share/opencode/auth.json
            test ! -d /home/brig/.config/claude
            test "$(stat -c %a "$CODEX_HOME")" = 700
        """,
        )
        self.agent(
            "integration-project",
            "opencode",
            "sh",
            "-ec",
            """
            umask 077
            printf '{"openai":{"type":"api","key":"brig-fixture-not-a-real-key"}}' > /home/brig/.local/share/opencode/auth.json
            printf private > /home/brig/.local/share/opencode/project/brig-test
            test ! -e /home/brig/.config/codex/auth.json
            test ! -d /home/brig/.config/claude
        """,
        )
        self.agent("other-project", "codex", "codex", "login", "status")
        self.agent("other-project", "opencode", "opencode", "auth", "list")
        self.agent("integration-project", "opencode", "opencode", "session", "list")
        self.agent(
            "integration-project",
            "opencode",
            "python",
            "-c",
            "import os, sqlite3; db = sqlite3.connect('file:' + os.environ['OPENCODE_DB'] + '?mode=rw', uri=True); "
            "db.execute('CREATE TABLE brig_fixture (marker TEXT)'); "
            "db.execute(\"INSERT INTO brig_fixture VALUES ('private')\"); db.commit()",
        )
        self.agent("other-project", "opencode", "opencode", "session", "list")
        self.agent(
            "other-project",
            "opencode",
            "python",
            "-c",
            "import os, sqlite3; db = sqlite3.connect('file:' + os.environ['OPENCODE_DB'] + '?mode=rw', uri=True); "
            "assert not db.execute(\"SELECT name FROM sqlite_master WHERE name = 'brig_fixture'\").fetchall()",
        )
        self.agent(
            "other-project",
            "codex",
            "sh",
            "-ec",
            """
            test -f "$CODEX_HOME/auth.json"
            test ! -f "$CODEX_HOME/sessions/brig-test"
            test ! -f "$CODEX_HOME/archived_sessions/brig-test"
            test ! -f /home/brig/.local/state/codex/brig-test
        """,
        )
        self.agent(
            "other-project",
            "opencode",
            "sh",
            "-ec",
            """
            test -f /home/brig/.local/share/opencode/auth.json
            test ! -f /home/brig/.local/share/opencode/project/brig-test
        """,
        )
        self.brig(
            "run",
            "integration-project",
            "--command",
            "sh",
            "-ec",
            """
            test ! -e /home/brig/.config/codex/auth.json
            test ! -e /home/brig/.local/share/opencode/auth.json
            test ! -d /home/brig/.config/claude
        """,
        )
        for agent in version.selected_agents:
            container = self.inspect(
                "container", f"brig-{self.project_id}-agent-{agent}"
            )
            self.assertEqual(container["Config"]["Labels"]["org.brig.agent"], agent)
            self.assertFalse(container["HostConfig"]["Privileged"])
        self.brig("down", "--project", "integration-project")
        self.agent("integration-project", "codex", "codex", "login", "status")
        self.agent(
            "integration-project",
            "codex",
            "sh",
            "-ec",
            """
            test -f "$CODEX_HOME/sessions/brig-test"
            test -f "$CODEX_HOME/archived_sessions/brig-test"
            test -f /home/brig/.local/state/codex/brig-test
        """,
        )
        self.agent(
            "integration-project",
            "opencode",
            "python",
            "-c",
            "import os, sqlite3; db = sqlite3.connect('file:' + os.environ['OPENCODE_DB'] + '?mode=rw', uri=True); "
            "assert db.execute('SELECT marker FROM brig_fixture').fetchone() == ('private',)",
        )
