"""Installer decisions with fake commands; never install host packages in tests."""

import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


class InstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = Path(__file__).resolve().parent.parent
        self.log = self.root / "commands"
        self.log.touch()

    def shell(self, code):
        return subprocess.run(
            ["bash", "-c", code],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "INSTALL_LOG": str(self.log),
                "DOCKER_HOST": "",
                "DOCKER_CONTEXT": "",
            },
            check=False,
        )

    def helper(self, code):
        # Every command that could change the host is replaced after sourcing.
        return self.shell(
            "set -euo pipefail\n"
            f"source {shlex.quote(str(self.repo / 'scripts/docker_dependencies.sh'))}\n"
            """
            cli=1
            compose=2.0.0
            accessible=1
            root_access=1
            configured_endpoint=unix:///var/run/docker.sock
            groups='developer docker'
            uname() { echo Linux; }
            id() {
                case "$1" in
                    -nG) echo "$groups" ;;
                    -un) echo developer ;;
                    -u) echo 1000 ;;
                esac
            }
            docker() {
                case "$1" in
                    --version) [[ "$cli" == 1 ]] ;;
                    compose) [[ "$compose" != missing ]] && echo "$compose" ;;
                    version) [[ "$accessible" == 1 ]] ;;
                    context) echo "$configured_endpoint" ;;
                    *) echo 'Unexpected Docker command' >&2; return 99 ;;
                esac
            }
            systemctl() { return 0; }
            dpkg() { echo amd64; }
            load_docker_platform() {
                docker_distribution=debian
                docker_codename=bookworm
            }
            as_root() {
                printf '%s\\n' "$*" >> "$INSTALL_LOG"
                case "$1" in
                    docker) [[ "$root_access" == 1 ]] ;;
                    systemctl) root_access=1 ;;
                    tee) cat >> "$INSTALL_LOG" ;;
                    apt-get)
                        if [[ "$*" == *docker-compose-plugin* ]]; then
                            compose=2.0.0
                            cli=1
                        fi
                        ;;
                esac
            }
            """ + code
        )

    def test_existing_accessible_installation_needs_no_system_changes(self):
        result = self.helper("ensure_docker")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accessible", result.stdout)
        self.assertEqual(self.log.read_text(), "")

    def test_missing_engine_installs_all_dependencies_without_removals(self):
        result = self.helper("cli=0; compose=missing; ensure_docker")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn(
            "install -y --no-remove --no-upgrade docker-compose-plugin docker-ce docker-ce-cli containerd.io docker-buildx-plugin",
            log,
        )
        self.assertNotIn("apt-get remove", log)

    def test_missing_compose_installs_only_plugin_and_keeps_engine(self):
        result = self.helper("compose=missing; ensure_docker")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn("install -y --no-remove --no-upgrade docker-compose-plugin", log)
        self.assertNotIn("docker-ce", log)

    def test_legacy_compose_is_repaired_but_newer_major_versions_are_supported(self):
        result = self.helper("compose=1.29.2; ensure_docker")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("docker-compose-plugin", self.log.read_text())
        self.log.write_text("")
        result = self.helper("compose=v3.1.0; ensure_docker")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), "")

    def test_stopped_local_daemon_is_started(self):
        result = self.helper(
            "accessible=0; root_access=0; groups=developer; ensure_docker"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn("systemctl enable --now docker", log)
        self.assertIn("usermod -aG docker developer", log)
        self.assertIn("Log out and back in", result.stdout)

    def test_user_access_is_configured_without_restarting_working_daemon(self):
        result = self.helper("accessible=0; groups=developer; ensure_docker")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usermod -aG docker developer", self.log.read_text())
        self.assertNotIn("systemctl", self.log.read_text())

    def test_cli_without_local_engine_installs_engine_before_starting_service(self):
        result = self.helper(
            "accessible=0; root_access=0; groups=developer; "
            "systemctl() { return 1; }; ensure_docker"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn("docker-ce docker-ce-cli containerd.io", log)
        self.assertLess(log.index("docker-ce"), log.index("systemctl enable --now"))

    def test_no_service_manager_gives_manual_start_instruction(self):
        result = self.helper(
            """
            accessible=0; root_access=0
            command() {
                if [[ "$*" == '-v systemctl' ]]; then return 1; fi
                builtin command "$@"
            }
            ensure_docker
            """
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Start the Docker daemon manually", result.stderr)

    def test_distribution_validation_uses_supported_release_metadata(self):
        helper = shlex.quote(str(self.repo / "scripts/docker_dependencies.sh"))
        for distro, codename, expected in (
            ("ubuntu", "noble", 0),
            ("debian", "trixie", 0),
            ("arch", "rolling", 1),
            ("ubuntu", "unknown", 1),
        ):
            with self.subTest(distro=distro, codename=codename):
                result = self.helper(
                    f"builtin source {helper}\n"
                    f"source() {{ ID={distro}; VERSION_CODENAME={codename}; "
                    "UBUNTU_CODENAME=''; PRETTY_NAME='test distribution'; }\n"
                    "load_docker_platform"
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn("unsupported", result.stderr)

    def test_remote_and_rootless_contexts_are_preserved_when_unreachable(self):
        for endpoint in ("ssh://server", "unix:///run/user/1000/docker.sock"):
            with self.subTest(endpoint=endpoint):
                self.log.write_text("")
                result = self.helper(
                    f"accessible=0; configured_endpoint={shlex.quote(endpoint)}; ensure_docker"
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("keeps your Docker context", result.stderr)
                self.assertEqual(self.log.read_text(), "")

    def test_docker_host_override_is_respected(self):
        result = self.helper(
            "accessible=0; DOCKER_HOST=tcp://server:2376; ensure_docker"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tcp://server:2376", result.stderr)
        self.assertEqual(self.log.read_text(), "")

    def test_remaining_socket_error_is_reported(self):
        result = self.helper("accessible=0; ensure_docker")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("session cannot access", result.stderr)
        self.assertNotIn("usermod", self.log.read_text())

    def test_failed_package_installation_stops_setup(self):
        result = self.helper(
            "cli=0; as_root() { echo blocked >&2; return 42; }; ensure_docker"
        )
        self.assertEqual(result.returncode, 42)
        self.assertNotIn("daemon is accessible", result.stdout)

    def test_unsupported_platform_and_failed_post_install_verification(self):
        result = self.helper("uname() { echo Darwin; }; ensure_docker")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires Linux", result.stderr)
        result = self.helper("cli=0; install_docker_packages() { :; }; ensure_docker")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be available after installation", result.stderr)

    def test_main_installer_installs_brig_after_validating_dependencies(self):
        binary = self.root / "bin"
        binary.mkdir()
        commands = {
            "id": "echo 1000",
            "uname": "echo Linux",
            "docker": "exit 0",
            "uv": 'printf \'%s\\n\' "$*" >> "$INSTALL_LOG"',
            "sudo": "echo 'Unexpected privilege escalation' >&2; exit 99",
        }
        for name, contents in commands.items():
            path = binary / name
            path.write_text("#!/usr/bin/env bash\n" + contents + "\n")
            path.chmod(0o755)
        # Compose must return a version; other Docker checks can return success.
        (binary / "docker").write_text(
            '#!/usr/bin/env bash\nif [[ "$1" == compose ]]; then echo 2.0.0; fi\n'
        )
        result = self.shell(
            f'export PATH={shlex.quote(str(binary))}:"$PATH"\n'
            f"bash {shlex.quote(str(self.repo / 'scripts/install.sh'))}"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().strip(), f"tool install --reinstall {self.repo}"
        )
