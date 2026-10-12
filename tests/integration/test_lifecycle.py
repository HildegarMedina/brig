"""Real CLI lifecycle with private temporary projects and automatic cleanup."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from brig.components.versions import LiveVersionCatalog
from brig.docker.engine import DockerEngine
from brig.docker.isolation import agent_uid
from brig.models import Profile, ProfileVersion, Project, State
from brig.persistence.store import JsonStateStore


@unittest.skipUnless(
    os.environ.get("BRIG_DOCKER_TESTS") == "1",
    "set BRIG_DOCKER_TESTS=1 to build and run Docker integration tests",
)
class DockerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="brig-integration-")
        self.directory = Path(self.temporary.name)
        self.data = self.directory / "data"
        self.source = self.directory / "source: ${BRIG_TEST_PATH}"
        self.source.mkdir()
        self.project_id = uuid4().hex
        self.other_id = uuid4().hex
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.remove_resources)
        version = ProfileVersion(
            1,
            {"python": os.environ.get("BRIG_TEST_PYTHON", "3.14.8")},
            {},
            {"redis": os.environ.get("BRIG_TEST_REDIS", "7.4.2")},
        )
        project = Project(
            self.project_id,
            "integration-project",
            str(self.source),
            "integration-profile",
            version,
        )
        other_source = self.directory / "other"
        other_source.mkdir()
        other = Project(
            self.other_id,
            "other-project",
            str(other_source),
            "integration-profile",
            version,
        )
        JsonStateStore(self.data).save(
            State([Profile("integration-profile", [version])], [project, other])
        )

    def remove_resources(self):
        # Only resources carrying these temporary test projects' exact IDs.
        for identifier in (self.project_id, self.other_id):
            prefix = f"brig-{identifier}"
            for kind, flags in (
                ("container", ["--all"]),
                ("network", []),
                ("volume", []),
            ):
                result = subprocess.run(
                    [
                        "docker",
                        kind,
                        "ls",
                        *flags,
                        "--filter",
                        f"label=org.brig.project-id={identifier}",
                        "--quiet",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                for resource in result.stdout.split():
                    subprocess.run(
                        [
                            "docker",
                            kind,
                            "rm",
                            *([] if kind == "network" else ["--force"]),
                            resource,
                        ],
                        capture_output=True,
                        check=False,
                    )
            result = subprocess.run(
                [
                    "docker",
                    "image",
                    "ls",
                    "--filter",
                    f"reference=brig-dev-{prefix}:*",
                    "--format",
                    "{{.Repository}}:{{.Tag}}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            for image in set(result.stdout.split()):
                subprocess.run(
                    ["docker", "image", "rm", image], capture_output=True, check=False
                )
        volume = DockerEngine(self.data / "runtime").agent_volume_name("claude")
        subprocess.run(
            ["docker", "volume", "rm", volume], capture_output=True, check=False
        )

    def brig(self, *args, success=True, cwd=None, input_data=None):
        result = subprocess.run(
            [sys.executable, "-m", "brig", "--data-dir", str(self.data), *args],
            cwd=cwd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def inspect(self, kind, name):
        result = subprocess.run(
            ["docker", kind, "inspect", name],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)[0]

    def test_run_builds_missing_image_mounts_only_project_and_preserves_data(self):
        prefix = f"brig-{self.project_id}"
        program = (
            "import os,pathlib,socket; "
            "assert os.getuid()==" + str(agent_uid("claude", os.getuid())) + "; "
            "assert pathlib.Path.cwd()==pathlib.Path('/workspace'); "
            "pathlib.Path('created_inside.txt').write_text('from container'); "
            "s=socket.create_connection(('redis',6379)); "
            "s.sendall(b'*3\\r\\n$3\\r\\nSET\\r\\n$4\\r\\nbrig\\r\\n$9\\r\\npersisted\\r\\n'); "
            "assert s.recv(1024)==b'+OK\\r\\n'; s.close(); print('isolated-project-ok')"
        )
        result = self.brig(
            "run", "integration-project", "--command", "python", "-c", program
        )
        self.assertIn("isolated-project-ok", result.stdout)
        result = self.brig(
            "agent",
            "claude",
            "--project",
            "integration-project",
            "--command",
            "claude",
            "--version",
        )
        self.assertIn("Claude Code", result.stdout)
        self.brig(
            "agent",
            "claude",
            "--project",
            "integration-project",
            "--command",
            "sh",
            "-ec",
            'test -f /usr/local/bin/claude; test ! -L /usr/local/bin/claude; echo retained > "$HOME/agent-test-config"',
        )
        self.assertEqual(
            (self.source / "created_inside.txt").read_text(), "from container"
        )
        first = self.inspect("container", prefix + "-dev")
        self.assertEqual(
            [mount["Source"] for mount in first["Mounts"] if mount["Type"] == "bind"],
            [str(self.source)],
        )
        self.assertFalse(first["HostConfig"]["Privileged"])
        self.assertFalse(
            self.inspect("container", prefix + "-redis")["HostConfig"]["PortBindings"]
        )
        result = self.brig("up", "--project", "integration-project")
        self.assertNotIn("Building image for", result.stderr)
        self.assertEqual(self.inspect("container", prefix + "-dev")["Id"], first["Id"])
        self.brig("down", "--project", "integration-project")
        self.assertTrue((self.source / "created_inside.txt").exists())
        self.inspect("volume", prefix + "-redis-data")
        result = self.brig(
            "run",
            "--command",
            "python",
            "-c",
            "import socket;s=socket.create_connection(('redis',6379));s.sendall(b'*2\\r\\n$3\\r\\nGET\\r\\n$4\\r\\nbrig\\r\\n');assert s.recv(1024)==b'$9\\r\\npersisted\\r\\n';print('data-preserved')",
            cwd=self.source,
        )
        self.assertIn("data-preserved", result.stdout)
        self.assertIn(
            "Claude Code",
            self.brig(
                "agent",
                "claude",
                "--project",
                "integration-project",
                "--command",
                "claude",
                "--version",
            ).stdout,
        )
        self.assertEqual(
            self.brig(
                "agent",
                "claude",
                "--project",
                "integration-project",
                "--command",
                "cat",
                "/opt/brig-agent-home/claude/agent-test-config",
            ).stdout.strip(),
            "retained",
        )
        self.brig("up", "--project", "other-project")
        self.brig(
            "agent",
            "claude",
            "--project",
            "integration-project",
            "--command",
            "sh",
            "-ec",
            'printf session-fixture > "$CLAUDE_CONFIG_DIR/session-test"; printf private-history > "$CLAUDE_CONFIG_DIR/projects/history-test"',
        )
        self.assertEqual(
            self.brig(
                "agent",
                "claude",
                "--project",
                "other-project",
                "--command",
                "sh",
                "-ec",
                'test ! -e "$CLAUDE_CONFIG_DIR/session-test"; test ! -e "$CLAUDE_CONFIG_DIR/projects/history-test"; printf isolated-settings',
            ).stdout,
            "isolated-settings",
        )
        other = self.inspect("container", f"brig-{self.other_id}-dev")
        self.assertNotEqual(
            set(first["NetworkSettings"]["Networks"]),
            set(other["NetworkSettings"]["Networks"]),
        )
        self.brig("down", "--project", "integration-project")
        self.assertTrue(
            self.inspect("container", f"brig-{self.other_id}-dev")["State"]["Running"]
        )

    def test_node_profile_runs_playwright_browser_and_claude(self):
        store = JsonStateStore(self.data)
        state = store.load()
        runtimes = {"node": os.environ.get("BRIG_TEST_NODE", "22.13.1")}
        version = (
            os.environ.get("BRIG_TEST_PLAYWRIGHT")
            or LiveVersionCatalog().compatible_versions("playwright", runtimes)[0]
        )
        version = ProfileVersion(2, runtimes, {"playwright": version}, {})
        state.profiles[0].versions.append(version)
        state.projects[0].configuration = version
        store.save(state)
        result = self.brig(
            "agent",
            "claude",
            "--project",
            "integration-project",
            "--command",
            "sh",
            "-ec",
            'node --version; claude --version; test -w "$CLAUDE_CONFIG_DIR"; test "$(stat -c %a "$CLAUDE_CONFIG_DIR")" = 700',
        )
        self.assertIn("Claude Code", result.stdout)
        self.assertIn("v" + version.runtimes["node"], result.stdout)
        browser = self.brig(
            "run",
            "integration-project",
            "--command",
            "node",
            "-e",
            """
            const http = require('http');
            const { chromium } = require('playwright');
            (async () => {
                const server = http.createServer((req, res) => res.end(`<button onclick="this.textContent='Clicked'">Click</button>`));
                await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
                const browser = await chromium.launch();
                try {
                    const page = await browser.newPage();
                    await page.goto('http://127.0.0.1:' + server.address().port);
                    await page.getByRole('button').click();
                    if (await page.getByRole('button').textContent() !== 'Clicked') throw Error('click failed');
                    await page.screenshot({path:'browser.png'});
                } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
                console.log('browser-automation-ok');
            })().catch(error => { console.error(error); process.exit(1); });
        """,
        )
        self.assertIn("browser-automation-ok", browser.stdout)
        self.assertTrue((self.source / "browser.png").is_file())

    def test_interactive_terminal_entry(self):
        import pty
        import select
        import time

        self.brig("up", "--project", "integration-project")
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "brig",
                "--data-dir",
                str(self.data),
                "run",
                "integration-project",
            ],
            stdin=slave,
            stdout=slave,
            stderr=slave,
        )
        os.close(slave)
        output = b""
        deadline = time.monotonic() + 60
        sent = False
        try:
            while time.monotonic() < deadline and process.poll() is None:
                ready, _, _ = select.select([master], [], [], 1)
                if ready:
                    try:
                        output += os.read(master, 65536)
                    except OSError:
                        break
                    if b"/workspace" in output and not sent:
                        os.write(
                            master, b"printf 'BRIG_TERMINAL_OK\\n'; pwd; id -u; exit\n"
                        )
                        sent = True
            self.assertEqual(
                process.wait(timeout=5), 0, output.decode(errors="replace")
            )
            self.assertTrue(sent, output.decode(errors="replace"))
            self.assertIn(b"BRIG_TERMINAL_OK", output)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def test_all_database_adapters_and_php_connections(self):
        store = JsonStateStore(self.data)
        state = store.load()
        version = ProfileVersion(
            2,
            {"php": os.environ.get("BRIG_TEST_PHP", "8.5.11")},
            {"composer": "2.10.3"},
            {
                "postgresql": "18.6",
                "mysql": "8.4.11",
                "mariadb": "11.4.4",
                "mongodb": "8.0.4",
                "redis": "7.4.2",
            },
        )
        state.profiles[0].versions.append(version)
        state.projects[0].configuration = version
        store.save(state)
        self.brig("up", "--project", "integration-project")
        code = """
            foreach (["MYSQL", "MARIADB"] as $prefix) {
                $pdo = new PDO("mysql:host=" . getenv($prefix . "_HOST") . ";dbname=brig", "brig", getenv($prefix . "_PASSWORD"));
                if ($pdo->query("SELECT 1")->fetchColumn() != 1) exit(1);
            }
            $pdo = new PDO("pgsql:host=" . getenv("PGHOST") . ";dbname=brig", "brig", getenv("PGPASSWORD"));
            if ($pdo->query("SELECT 1")->fetchColumn() != 1) exit(1);
            foreach (["mongodb" => 27017, "redis" => 6379] as $host => $port) {
                $connection = fsockopen($host, $port, $errno, $message, 10);
                if (!$connection) exit(1);
                fclose($connection);
            }
            echo "all-service-connections-ok";
        """
        result = self.brig("run", "integration-project", "--command", "php", "-r", code)
        self.assertIn("all-service-connections-ok", result.stdout)
        clients = self.brig(
            "run",
            "integration-project",
            "--command",
            "sh",
            "-ec",
            """
            curl --version >/dev/null
            printf '{"ok":true}' | jq -e '.ok' >/dev/null
            printf 'searchable-code' | rg 'searchable' >/dev/null
            test "$(psql -Atc 'SELECT 1')" = 1
            test "$(MYSQL_PWD="$MYSQL_PASSWORD" mysql -h mysql -u brig -D brig -Nse 'SELECT 1')" = 1
            test "$(MYSQL_PWD="$MARIADB_PASSWORD" mysql -h mariadb -u brig -D brig -Nse 'SELECT 1')" = 1
            mongosh "$MONGODB_URI" --quiet --eval 'quit(db.runCommand({ping:1}).ok ? 0 : 1)'
            test "$(redis-cli -h redis ping)" = PONG
            echo all-development-clients-ok
        """,
        )
        self.assertIn("all-development-clients-ok", clients.stdout)
        self.assertIn(
            "Claude Code",
            self.brig(
                "agent",
                "claude",
                "--project",
                "integration-project",
                "--command",
                "claude",
                "--version",
            ).stdout,
        )
        mongo = subprocess.run(
            [
                "docker",
                "exec",
                f"brig-{self.project_id}-mongodb",
                "sh",
                "-ec",
                'mongosh --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --eval "quit(db.adminCommand({ping:1}).ok ? 0 : 1)"',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(mongo.returncode, 0, mongo.stderr)
        for name in version.services:
            container = self.inspect("container", f"brig-{self.project_id}-{name}")
            self.assertEqual(container["State"]["Health"]["Status"], "healthy")
            self.assertFalse(container["HostConfig"]["PortBindings"])
