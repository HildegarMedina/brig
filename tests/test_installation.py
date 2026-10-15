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

    def installer(self, *arguments, commands=None, environment=None, terminal=False):
        binary = self.root / "bin"
        binary.mkdir(exist_ok=True)
        programs = {
            "id": "echo 1000",
            "uname": "echo Linux",
            "docker": 'if [[ "$1" == compose ]]; then echo 2.0.0; fi',
            "uv": (
                'printf \'%s\\n\' "$*" >> "$INSTALL_LOG"\n'
                "echo 'package build detail'\n"
                "echo 'resolver detail' >&2"
            ),
            "sudo": "echo 'Unexpected privilege escalation' >&2; exit 99",
            "brig": "exit 0",
            **(commands or {}),
        }
        for name, contents in programs.items():
            path = binary / name
            path.write_text("#!/usr/bin/env bash\n" + contents + "\n")
            path.chmod(0o755)
        command = ["bash", str(self.repo / "scripts/install.sh"), *arguments]
        env = {
            **os.environ,
            "PATH": str(binary) + os.pathsep + os.environ["PATH"],
            "INSTALL_LOG": str(self.log),
            "TMPDIR": str(self.root),
            "DOCKER_HOST": "",
            "DOCKER_CONTEXT": "",
            "BRIG_LANG": "en",
            **(environment or {}),
        }
        if not terminal:
            return subprocess.run(
                command, capture_output=True, text=True, env=env, check=False
            )
        master, slave = os.openpty()
        output = bytearray()
        try:
            with subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=slave, env=env, text=True
            ) as process:
                os.close(slave)
                stdout, _ = process.communicate(timeout=5)
                while True:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break  # Linux PTYs report EIO when the slave closes.
                    if not chunk:
                        break
                    output.extend(chunk)
            return subprocess.CompletedProcess(
                command, process.returncode, stdout, output.decode()
            )
        finally:
            os.close(master)

    def test_main_installer_installs_brig_after_validating_dependencies(self):
        result = self.installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().strip(), f"tool install --reinstall {self.repo}"
        )
        self.assertIn("BRIG / Installer", result.stderr)
        self.assertIn("Preparing Docker...", result.stderr)
        self.assertIn("Installing Brig...", result.stderr)
        self.assertIn("Run: brig", result.stderr)
        self.assertIn(r"|\|\__/", result.stderr)
        self.assertNotIn("package build detail", result.stdout + result.stderr)
        self.assertNotIn("resolver detail", result.stdout + result.stderr)
        self.assertNotIn("daemon is accessible", result.stderr)
        self.assertNotIn("\033", result.stderr)
        self.assertEqual(list(self.root.glob("tmp.*")), [])

    def test_verbose_installer_shows_live_details(self):
        result = self.installer("--verbose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("package build detail", result.stdout)
        self.assertIn("resolver detail", result.stderr)
        self.assertIn("daemon is accessible", result.stdout)

    def test_terminal_presentation_and_animation_preferences(self):
        for preferences, animated in (
            ({}, True),
            ({"BRIG_NO_ANIMATION": "1"}, False),
            ({"CI": "1"}, False),
            ({"TERM": "dumb"}, False),
        ):
            with self.subTest(preferences=preferences):
                result = self.installer(
                    terminal=True,
                    commands={"uv": "sleep 0.25", "tput": "echo 80"},
                    environment={
                        "TERM": "xterm",
                        "NO_COLOR": "",
                        "CI": "",
                        "BRIG_NO_ANIMATION": "",
                        **preferences,
                    },
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(r"/_|_\/_|_", result.stderr)
                self.assertIn("Brig installed.", result.stderr)
                self.assertEqual("\033[2K" in result.stderr, animated)
                self.assertNotIn("\033[36m", result.stderr)
                self.assertEqual(list(self.root.glob("tmp.*")), [])

    def test_small_terminal_uses_compact_boat_without_animation(self):
        result = self.installer(
            terminal=True,
            commands={"tput": "echo 20"},
            environment={"TERM": "xterm", "NO_COLOR": ""},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(r"|\|\__/", result.stderr)
        self.assertNotIn("\033", result.stderr)

    def test_failed_installer_limits_technical_output(self):
        result = self.installer(
            commands={
                "uv": 'for ((i=1; i<=50; i++)); do echo "line $i"; done; exit 9',
            }
        )
        self.assertEqual(result.returncode, 9)
        self.assertNotIn("\nline 20\n", result.stderr)
        self.assertIn("\nline 21\n", result.stderr)
        self.assertIn("\nline 50\n", result.stderr)

    def test_failed_installation_reveals_diagnostics_preserves_exit_and_cleans_log(
        self,
    ):
        result = self.installer(commands={"uv": "echo 'expected failure' >&2; exit 42"})
        self.assertEqual(result.returncode, 42)
        self.assertIn("Could not complete: Installing Brig", result.stderr)
        self.assertIn("expected failure", result.stderr)
        self.assertNotIn("Brig installed.", result.stderr)
        self.assertEqual(list(self.root.glob("tmp.*")), [])

    def test_nested_docker_failure_is_visible_and_never_installs_brig(self):
        result = self.installer(
            commands={
                "docker": 'case "$1" in compose) echo 2.0.0 ;; version) exit 1 ;; context) echo ssh://server ;; esac',
            }
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not complete: Preparing Docker", result.stderr)
        self.assertIn("keeps your Docker context", result.stderr)
        self.assertNotIn("Installing Brig...", result.stderr)
        self.assertEqual(self.log.read_text(), "")
        self.assertEqual(list(self.root.glob("tmp.*")), [])

    def test_installer_preserves_the_required_login_notice(self):
        result = self.installer(
            commands={
                "docker": 'case "$1" in compose) echo 2.0.0 ;; version) exit 1 ;; context) echo unix:///var/run/docker.sock ;; esac',
                "id": 'case "$1" in -u) echo 1000 ;; -nG) echo developer ;; -un) echo developer ;; esac',
                "sudo": "exit 0",
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Log out and back in before using environments.", result.stderr)
        self.assertNotIn("usermod", result.stderr)

    def test_installer_languages_use_brief_localized_labels(self):
        for language, ready in (("es", "Brig instalado."), ("pt", "Brig instalado.")):
            with self.subTest(language=language):
                result = self.installer(environment={"BRIG_LANG": language})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("BRIG / Instalador", result.stderr)
                self.assertIn("Preparando Docker...", result.stderr)
                self.assertIn("Instalando Brig...", result.stderr)
                self.assertIn(ready, result.stderr)

    def test_help_and_invalid_options_do_not_install_anything(self):
        for options, expected in (
            (("--help",), 0),
            (("--unknown",), 2),
            (("--verbose", "extra"), 2),
        ):
            with self.subTest(options=options):
                result = self.installer(*options)
                self.assertEqual(result.returncode, expected)
                self.assertIn("Usage:", result.stdout + result.stderr)
                self.assertEqual(self.log.read_text(), "")
