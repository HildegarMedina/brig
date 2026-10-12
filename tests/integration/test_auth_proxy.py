"""Boot the real unprivileged proxy from privately generated sources."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from brig.docker.auth_proxy import proxy_image_lines, proxy_sources
from brig.docker.workspace import DockerWorkspace


@unittest.skipUnless(
    os.environ.get("BRIG_DOCKER_TESTS") == "1",
    "set BRIG_DOCKER_TESTS=1 to build the credential proxy",
)
class CredentialProxyTests(unittest.TestCase):
    def test_private_sources_boot_as_unprivileged_user(self):
        image = f"brig-proxy-test:{uuid4().hex}"
        with tempfile.TemporaryDirectory(prefix="brig-proxy-test-") as folder:
            directory = Path(folder)
            for name, content in proxy_sources().items():
                DockerWorkspace.write(directory / name, content)
            self.assertEqual((directory / "proxy/brig").stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                (directory / "proxy/brig/__init__.py").stat().st_mode & 0o777, 0o600
            )
            DockerWorkspace.write(
                directory / "Dockerfile", "\n".join(proxy_image_lines())
            )
            self.addCleanup(
                subprocess.run,
                ["docker", "image", "rm", image],
                capture_output=True,
                check=False,
            )
            build = subprocess.run(
                ["docker", "build", "--tag", image, str(directory)],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        program = """
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

assert os.getuid() != 0
process = subprocess.Popen([sys.executable, '-m', 'brig.auth_proxy'])
try:
    for attempt in range(100):
        assert process.poll() is None, 'proxy exited during startup'
        if Path('/public/ready').exists():
            with socket.create_connection(('127.0.0.1', 8080), 2):
                pass
            assert Path('/public/auth.json').is_file()
            assert Path('/public/cert.pem').is_file()
            break
        time.sleep(0.1)
    else:
        raise AssertionError('proxy never became ready')
finally:
    process.terminate()
    process.wait(timeout=10)
"""
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--env",
                "BRIG_AUTH_AGENT=codex",
                image,
                "python",
                "-c",
                program,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
