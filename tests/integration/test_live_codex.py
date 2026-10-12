"""Optional real Codex task using the host's protected login, without reading it."""

import os
import subprocess
import unittest

from brig.application import Application
from brig.docker.engine import DockerEngine
from brig.models import ProfileVersion
from brig.persistence.store import JsonStateStore, default_data_directory
from tests.integration import test_lifecycle


@unittest.skipUnless(
    os.environ.get("BRIG_LIVE_CODEX_TESTS") == "1",
    "set BRIG_LIVE_CODEX_TESTS=1 to use the host's Codex login and account quota",
)
class LiveCodexTests(unittest.TestCase):
    setUp = test_lifecycle.DockerLifecycleTests.setUp
    remove_resources = test_lifecycle.DockerLifecycleTests.remove_resources

    def test_real_task_uses_shared_login_and_keeps_history_per_project(self):
        executions = []

        def runner(args, **options):
            if args[:2] == ["docker", "exec"]:
                options.update(capture_output=True, text=True, timeout=180)
                result = subprocess.run(args, **options)
                executions.append(result)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            return subprocess.run(args, **options)

        store = JsonStateStore(self.data)
        state = store.load()
        version = ProfileVersion(
            2,
            {"python": os.environ.get("BRIG_TEST_PYTHON", "3.14.8")},
            {},
            {},
            agent="codex",
            agents=["codex"],
        )
        state.profiles[0].versions.append(version)
        for project in state.projects:
            project.configuration = version
        store.save(state)
        # Separate registrations and sources, but the same protected login scope.
        engine = DockerEngine(default_data_directory() / "runtime", runner=runner)
        app = Application(store, engine)
        app.shell("integration-project", ["codex", "--version"])
        self.assertTrue(executions[-1].stdout.strip())
        app.run_agent(
            "integration-project",
            "codex",
            [
                "codex",
                "exec",
                "--skip-git-repo-check",
                "Create brig-e2e.txt in the current directory containing exactly "
                "BRIG_E2E_OK followed by a newline. Do not read any other files. "
                "Respond only with OK when finished.",
            ],
        )
        self.assertEqual((self.source / "brig-e2e.txt").read_text(), "BRIG_E2E_OK\n")
        check = (
            "from pathlib import Path; import json; "
            "home=Path('/opt/brig-agent-home/codex/.config/codex'); "
            "assert list((home/'sessions').rglob('*.jsonl')); "
            "auth=json.loads((home/'auth.json').read_text()); "
            "assert auth['tokens']['refresh_token']=='sk-brig-proxy-managed-not-a-real-credential'; "
            "assert not Path('/secrets').exists(); "
            "assert not Path('/certificates').exists(); "
            "print('BRIG_HISTORY_AND_CREDENTIAL_BOUNDARY_OK')"
        )
        app.shell("integration-project", ["python", "-c", check])
        self.assertIn("BRIG_HISTORY_AND_CREDENTIAL_BOUNDARY_OK", executions[-1].stdout)
        app.stop("integration-project")
        app.shell("integration-project", ["python", "-c", check])
        app.shell(
            "other-project",
            [
                "python",
                "-c",
                "from pathlib import Path; assert not list(Path('/opt/brig-agent-home/codex/.config/codex/sessions').rglob('*.jsonl'))",
            ],
        )
