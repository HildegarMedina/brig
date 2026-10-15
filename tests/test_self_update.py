"""Brig release integrity, daily scheduling, pinning, and isolated self-management."""

import hashlib
import io
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from brig import __version__
from brig.errors import BrigError
from brig.releases import (
    LATEST,
    REQUIREMENTS,
    fetch,
    latest_version,
    newer,
    release_files,
    stable_version,
)
from brig.self_update import (
    INTERVAL,
    STATE_FILE,
    automatic_check,
    check_worker,
    command,
    read_state,
    refresh,
    save_state,
    state_lock,
    update,
    uv_executable,
)
from brig.ui.cli import main


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_only_exact_stable_release_versions_can_be_installed(self):
        for value in ("1.0.0", "v1.0.0", "12.10.32"):
            self.assertEqual(stable_version(value), value.removeprefix("v"))
        for value in (
            None,
            1,
            "",
            "main",
            "1.0",
            "01.0.0",
            "1.0.0rc1",
            "1.0.0/../../file",
            "$(touch file)",
        ):
            with self.subTest(value=value), self.assertRaises(BrigError):
                stable_version(value)
        self.assertTrue(newer("1.0.10", "1.0.9"))
        self.assertFalse(newer("1.0.0"))

    def test_bounded_https_transport_uses_the_release_identity(self):
        response = Mock(url="https://release-assets.githubusercontent.com/fixture")
        response.read.return_value = b"data"
        with patch("brig.releases.urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            self.assertEqual(fetch(LATEST, limit=4), b"data")
            request = open_url.call_args.args[0]
            self.assertEqual(request.get_header("User-agent"), f"brig/{__version__}")
            response.read.assert_called_once_with(5)
            response.read.return_value = b"large"
            with self.assertRaises(ValueError):
                fetch(LATEST, limit=4)
            response.url = "http://example.com/fixture"
            with self.assertRaises(ValueError):
                fetch(LATEST)

    def test_latest_release_filters_invalid_drafts_and_pre_releases(self):
        download = Mock(
            return_value=b'{"tag_name":"v1.0.1","draft":false,"prerelease":false}'
        )
        self.assertEqual(latest_version(download=download), "1.0.1")
        download.assert_called_once_with(LATEST, limit=256 * 1024)
        for payload in (
            b"bad",
            b"[]",
            b"null",
            b"{}",
            b'{"tag_name":"v1.0.1rc1"}',
            b'{"tag_name":"v1.0.1","draft":true}',
            b'{"tag_name":"v1.0.1","prerelease":true}',
        ):
            with self.subTest(payload=payload), self.assertRaises(BrigError):
                latest_version(download=Mock(return_value=payload))
        with self.assertRaises(BrigError):
            latest_version(download=Mock(side_effect=OSError("offline")))

    def assets(self):
        return {
            "brig-1.0.1-py3-none-any.whl": b"fixture-wheel",
            REQUIREMENTS: b"packaging==26.3\n",
        }

    def test_package_and_dependency_lock_are_verified_before_use(self):
        assets = self.assets()
        manifest = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data in assets.items()
        ).encode()

        def download(url, **kwargs):
            self.assertTrue(
                url.startswith(
                    "https://github.com/HildegarMedina/brig/releases/download/v1.0.1/"
                )
            )
            return (
                manifest
                if url.endswith("SHA256SUMS")
                else assets[url.rsplit("/", 1)[1]]
            )

        wheel, constraints = release_files("v1.0.1", self.root, download=download)
        self.assertEqual(wheel.read_bytes(), assets[wheel.name])
        self.assertEqual(constraints.read_bytes(), assets[constraints.name])

    def test_missing_malformed_duplicate_traversal_or_mismatched_checksums_fail(self):
        digest = hashlib.sha256(b"fixture-wheel").hexdigest()
        valid = f"{digest}  brig-1.0.1-py3-none-any.whl\n"
        for manifest in (
            b"",
            b"not-a-manifest",
            b"zz  file\n",
            b"\xff",
            (valid + valid).encode(),
            f"{digest} ../file\n".encode(),
            f"{digest} path\\file\n".encode(),
            valid.encode(),
            (valid + f"{'0' * 64} {REQUIREMENTS}\n").encode(),
        ):

            def download(url, manifest=manifest, **kwargs):
                return manifest if url.endswith("SHA256SUMS") else b"tampered"

            with self.subTest(manifest=manifest), self.assertRaises(BrigError):
                release_files("1.0.1", self.root, download=download)
        with self.assertRaises(BrigError):
            release_files(
                "1.0.1", self.root, download=Mock(side_effect=OSError("offline"))
            )


class SelfUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "data"
        env = patch.dict(
            os.environ, {"BRIG_NO_SELF_UPDATE_CHECK": "", "BRIG_LANG": "en"}
        )
        env.start()
        self.addCleanup(env.stop)

    def test_daily_checks_reserve_a_single_attempt_even_on_failure(self):
        with (
            patch("brig.self_update.subprocess.Popen") as launch,
            patch("brig.self_update.time.time", return_value=100),
        ):
            self.assertEqual(automatic_check(self.root), "")
            automatic_check(self.root)
            launch.assert_called_once()
            self.assertEqual(read_state(self.root)["checked_at"], 100)
            self.assertTrue(launch.call_args.kwargs["start_new_session"])
            self.assertEqual(launch.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(launch.call_args.args[0][-1], str(self.root.absolute()))
        with (
            patch(
                "brig.self_update.subprocess.Popen", side_effect=OSError("blocked")
            ) as launch,
            patch("brig.self_update.time.time", return_value=100 + INTERVAL),
        ):
            self.assertEqual(automatic_check(self.root), "")
            automatic_check(self.root)
            launch.assert_called_once()
            self.assertEqual(read_state(self.root)["checked_at"], 100 + INTERVAL)

    def test_parallel_commands_only_launch_one_worker(self):
        with (
            patch("brig.self_update.subprocess.Popen") as launch,
            patch("brig.self_update.time.time", return_value=100),
        ):
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(lambda _: automatic_check(self.root), range(20)))
            launch.assert_called_once()

    def test_cached_notices_versions_and_future_timestamps(self):
        save_state(self.root, {"checked_at": 100, "available": "1.0.1"})
        with (
            patch("brig.self_update.time.time", return_value=101),
            patch("brig.self_update.subprocess.Popen") as launch,
        ):
            self.assertIn("1.0.1", automatic_check(self.root))
            launch.assert_not_called()
            save_state(self.root, {"checked_at": 200, "available": "1.0.0"})
            self.assertEqual(automatic_check(self.root), "")
            launch.assert_called_once()
            save_state(self.root, {"checked_at": 100, "available": "bad"})
            self.assertEqual(automatic_check(self.root), "")
        with (
            patch.dict(os.environ, {"BRIG_NO_SELF_UPDATE_CHECK": "1"}),
            patch("brig.self_update.subprocess.Popen") as launch,
        ):
            self.assertEqual(automatic_check(self.root), "")
            launch.assert_not_called()

    def test_corrupt_or_busy_settings_do_not_break_normal_commands(self):
        self.assertEqual(read_state(self.root), {})
        self.root.mkdir()
        for contents in ("{", "[]"):
            (self.root / STATE_FILE).write_text(contents)
            self.assertEqual(automatic_check(self.root), "")
            with self.assertRaises(BrigError):
                command(self.root, "pin")
        save_state(self.root, {})
        with state_lock(self.root):
            self.assertEqual(automatic_check(self.root), "")
            with self.assertRaisesRegex(BrigError, "Retry"):
                command(self.root, "pin")

    def test_worker_caches_success_and_failed_attempts_without_erasing_policy(self):
        save_state(self.root, {"pinned": "1.0.0", "available": "1.0.1"})
        with (
            patch("brig.self_update.latest_version", side_effect=BrigError("offline")),
            patch("brig.self_update.time.time", return_value=100),
        ):
            check_worker(self.root)
        self.assertEqual(
            read_state(self.root),
            {"pinned": "1.0.0", "available": "1.0.1", "checked_at": 100},
        )
        with patch("brig.self_update.latest_version", return_value="1.0.2"):
            self.assertEqual(refresh(self.root), "1.0.2")
        self.assertEqual(read_state(self.root)["available"], "1.0.2")
        with (
            warnings.catch_warnings(),
            patch("brig.releases.latest_version", return_value="1.0.3"),
            patch.object(sys, "argv", ["brig.self_update", str(self.root)]),
        ):
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("brig.self_update", run_name="__main__")
        self.assertEqual(read_state(self.root)["available"], "1.0.3")

    def test_pin_blocks_automatic_and_explicit_upgrades_until_unpinned(self):
        self.assertIn("1.0.0", command(self.root, "pin"))
        with patch("brig.self_update.subprocess.Popen") as launch:
            self.assertEqual(automatic_check(self.root), "")
            launch.assert_not_called()
        for target in (None, "1.0.1"):
            with self.assertRaisesRegex(BrigError, "unpin"):
                command(self.root, "update", target)
        self.assertIn("enabled", command(self.root, "unpin"))
        self.assertNotIn("pinned", read_state(self.root))
        with patch("brig.self_update.latest_version", return_value="1.0.1"):
            self.assertIn("1.0.1", command(self.root, "check"))
        with patch("brig.self_update.latest_version", return_value="1.0.0"):
            self.assertIn("up to date", command(self.root, "check"))
            self.assertIn("up to date", update(self.root))

    def test_uv_detection_uses_path_or_the_users_local_installation(self):
        with patch("brig.self_update.shutil.which", return_value="/fixture/uv"):
            self.assertEqual(uv_executable(), "/fixture/uv")
        location = self.root / "bin"
        location.mkdir(parents=True)
        binary = location / "uv"
        binary.write_text("fixture")
        binary.chmod(0o755)
        for environment in (
            {"UV_INSTALL_DIR": str(location), "XDG_BIN_HOME": ""},
            {"UV_INSTALL_DIR": "", "XDG_BIN_HOME": str(location)},
        ):
            with (
                patch("brig.self_update.shutil.which", return_value=None),
                patch.dict(os.environ, environment),
            ):
                self.assertEqual(uv_executable(), str(binary))
        with (
            patch("brig.self_update.shutil.which", return_value=None),
            patch.dict(os.environ, {"UV_INSTALL_DIR": "", "XDG_BIN_HOME": ""}),
            patch("brig.self_update.Path.home", return_value=self.root),
            self.assertRaisesRegex(BrigError, "requires uv"),
        ):
            uv_executable()

    def fixture_files(self, version, directory):
        wheel = directory / f"brig-{version}-py3-none-any.whl"
        lock = directory / REQUIREMENTS
        wheel.write_text("fixture")
        lock.write_text("packaging==26.3\n")
        return wheel, lock

    def test_verified_exact_versions_install_with_constraints_and_no_docker(self):
        for target in ("1.0.0", "0.9.0", None):
            with (
                patch("brig.self_update.latest_version", return_value="1.0.1"),
                patch("brig.self_update.uv_executable", return_value="/fixture/uv"),
                patch("brig.self_update.release_files", side_effect=self.fixture_files),
                patch("brig.self_update.subprocess.run") as install,
            ):
                result = command(self.root, "update", target)
                self.assertIn(target or "1.0.1", result)
                args = install.call_args.args[0]
                self.assertEqual(
                    args[:7],
                    [
                        "/fixture/uv",
                        "tool",
                        "install",
                        "--python",
                        ">=3.12",
                        "--reinstall",
                        "--constraints",
                    ],
                )
                self.assertTrue(
                    args[-1].endswith(f"brig-{target or '1.0.1'}-py3-none-any.whl")
                )
                self.assertFalse(Path(args[-1]).exists())
                install.assert_called_once()
        command(self.root, "pin")
        with (
            patch("brig.self_update.uv_executable", return_value="/fixture/uv"),
            patch("brig.self_update.release_files", side_effect=self.fixture_files),
            patch("brig.self_update.subprocess.run"),
        ):
            self.assertIn("1.0.0", command(self.root, "update", "1.0.0"))

    def test_failed_verification_never_runs_uv_and_install_errors_are_clear(self):
        with (
            patch("brig.self_update.uv_executable", return_value="/fixture/uv"),
            patch("brig.self_update.release_files", side_effect=BrigError("checksum")),
            patch("brig.self_update.subprocess.run") as install,
        ):
            with self.assertRaisesRegex(BrigError, "checksum"):
                command(self.root, "update", "1.0.1")
            install.assert_not_called()
        for error in (OSError("blocked"), subprocess.CalledProcessError(1, "uv")):
            with (
                patch("brig.self_update.uv_executable", return_value="/fixture/uv"),
                patch("brig.self_update.release_files", side_effect=self.fixture_files),
                patch("brig.self_update.subprocess.run", side_effect=error),
                self.assertRaisesRegex(BrigError, "update failed"),
            ):
                command(self.root, "update", "1.0.1")

    def test_a_pin_set_during_download_stops_installation(self):
        def download(version, directory):
            command(self.root, "pin")
            return self.fixture_files(version, directory)

        with (
            patch("brig.self_update.uv_executable", return_value="/fixture/uv"),
            patch("brig.self_update.release_files", side_effect=download),
            patch("brig.self_update.subprocess.run") as install,
        ):
            with self.assertRaisesRegex(BrigError, "unpin"):
                command(self.root, "update", "1.0.1")
            install.assert_not_called()

    def test_cli_self_commands_do_not_construct_docker_or_require_a_project(self):
        output = io.StringIO()
        with (
            patch("brig.ui.cli.DockerEngine", side_effect=AssertionError("Docker")),
            redirect_stdout(output),
        ):
            self.assertEqual(main(["--data-dir", str(self.root), "self", "pin"]), 0)
            self.assertEqual(main(["--data-dir", str(self.root), "self", "unpin"]), 0)
        self.assertIn("1.0.0", output.getvalue())
        errors = io.StringIO()
        with (
            redirect_stderr(errors),
            patch("brig.self_update.latest_version", side_effect=BrigError("offline")),
        ):
            self.assertEqual(main(["--data-dir", str(self.root), "self", "check"]), 1)
        self.assertIn("offline", errors.getvalue())

    def test_real_cli_checks_help_and_keeps_pipes_free_of_notices(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True

        for interactive in (False, True):
            output = Terminal() if interactive else io.StringIO()
            errors = Terminal() if interactive else io.StringIO()
            with (
                patch.object(
                    sys, "argv", ["brig", "--data-dir", str(self.root), "--help"]
                ),
                patch("brig.ui.cli._main", return_value=0),
                patch(
                    "brig.ui.cli.automatic_check", return_value="update notice"
                ) as check,
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                self.assertEqual(main(), 0)
                check.assert_called_once_with(self.root)
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(
                    errors.getvalue(), "update notice\n" if interactive else ""
                )
        with (
            patch.object(
                sys, "argv", ["brig", "--data-dir", str(self.root), "self", "check"]
            ),
            patch("brig.ui.cli._main", return_value=0),
            patch("brig.ui.cli.automatic_check") as check,
        ):
            self.assertEqual(main(), 0)
            check.assert_not_called()
