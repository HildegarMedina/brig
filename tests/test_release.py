"""Release artifact generation and remote installation without network or Docker."""

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from brig import __version__
from brig.releases import REQUIREMENTS
from scripts import build_release
from tests import test_installation


class ReleaseBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def build_command(self, args, **kwargs):
        if args[1] == "export":
            Path(args[-1]).write_bytes(
                (build_release.ROOT / "src/brig/release/requirements.txt").read_bytes()
            )
        else:
            output = Path(args[-1])
            staging = Path(args[2])
            self.assertTrue((staging / "pyproject.toml").is_file())
            self.assertFalse((staging / "build").exists())
            with ZipFile(
                output / f"brig-{__version__}-py3-none-any.whl", "w"
            ) as archive:
                archive.writestr(
                    f"brig-{__version__}.dist-info/METADATA",
                    f"Metadata-Version: 2.4\nName: brig\nVersion: {__version__}\n",
                )
                archive.writestr(
                    "brig/release/requirements.txt",
                    (staging / "src/brig/release/requirements.txt").read_bytes(),
                )

    def test_build_checks_the_version_and_produces_verified_standalone_assets(self):
        with patch(
            "scripts.build_release.subprocess.run", side_effect=self.build_command
        ):
            assets = build_release.build(self.root, "v1.0.0")
        self.assertEqual(
            {path.name for path in assets},
            {
                "brig-1.0.0-py3-none-any.whl",
                REQUIREMENTS,
                "install.sh",
                "VERSION",
                "SHA256SUMS",
            },
        )
        for line in (self.root / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split()
            self.assertEqual(
                digest, hashlib.sha256((self.root / name).read_bytes()).hexdigest()
            )
        script = (self.root / "install.sh").read_text()
        self.assertIn("release_version='1.0.0'", script)
        self.assertNotIn("@BRIG_", script)
        self.assertNotIn(str(build_release.ROOT), script)
        result = subprocess.run(
            ["bash", "-n", str(self.root / "install.sh")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaisesRegex(ValueError, "tag"):
            build_release.build(self.root, "v1.0.1")

    def test_stale_constraints_stop_the_release_before_building_a_package(self):
        def export(args, **kwargs):
            Path(args[-1]).write_text("packaging==0.0.0\n")

        with (
            patch("scripts.build_release.subprocess.run", side_effect=export) as run,
            self.assertRaisesRegex(ValueError, "stale"),
        ):
            build_release.build(self.root)
        run.assert_called_once()


class RemoteInstallationTests(unittest.TestCase):
    def setUp(self):
        self.case = test_installation.InstallationTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.root
        self.script = self.root / "remote installer.sh"
        self.script.write_text(build_release.render_installer(__version__))
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.release_assets()

    def release_assets(self, version="1.0.0"):
        assets = {
            f"brig-{version}-py3-none-any.whl": b"fixture-wheel",
            REQUIREMENTS: b"packaging==26.3\n",
        }
        for name, data in assets.items():
            (self.assets / name).write_bytes(data)
        (self.assets / "SHA256SUMS").write_text(
            "".join(
                f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                for name, data in assets.items()
            )
        )

    def installer(self, *args, commands=None):
        curl = """source_url=''
destination=''
for arg in "$@"; do
    case "$arg" in https://*) source_url=$arg ;; esac
done
while [[ $# -gt 0 ]]; do
    if [[ "$1" == --output ]]; then destination=$2; break; fi
    shift
done
printf 'download %s\\n' "$source_url" >> "$INSTALL_LOG"
cat "$RELEASE_FIXTURE/${source_url##*/}" > "$destination"
"""
        wget = """source_url=''
destination=''
for arg in "$@"; do
    case "$arg" in
        https://*) source_url=$arg ;;
        --output-document=*) destination=${arg#--output-document=} ;;
    esac
done
printf 'download %s\\n' "$source_url" >> "$INSTALL_LOG"
cat "$RELEASE_FIXTURE/${source_url##*/}" > "$destination"
"""
        return self.case.installer(
            *args,
            script=self.script,
            commands={"curl": curl, "wget": wget, **(commands or {})},
            environment={"RELEASE_FIXTURE": str(self.assets)},
        )

    def test_remote_installer_downloads_only_the_pinned_release_and_lock(self):
        result = self.installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.case.log.read_text()
        self.assertIn("/releases/download/v1.0.0/brig-1.0.0-py3-none-any.whl", log)
        self.assertIn("/releases/download/v1.0.0/brig-requirements.txt", log)
        self.assertIn("--constraints", log)
        self.assertIn("tool update-shell", log)
        self.assertNotIn("git clone", log)
        self.assertIn("Brig installed.", result.stderr)
        self.assertEqual(list(self.root.glob("brig-release.*")), [])
        self.release_assets("0.9.0")
        result = self.installer("--version", "v0.9.0", commands={"curl": None})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "/releases/download/v0.9.0/brig-0.9.0-py3-none-any.whl",
            self.case.log.read_text(),
        )

    def test_bad_or_incomplete_checksums_never_start_package_installation(self):
        for mutation in ("wheel", "constraints", "missing", "duplicate"):
            with self.subTest(mutation=mutation):
                self.release_assets()
                self.case.log.write_text("")
                if mutation in ("wheel", "constraints"):
                    name = (
                        "brig-1.0.0-py3-none-any.whl"
                        if mutation == "wheel"
                        else REQUIREMENTS
                    )
                    (self.assets / name).write_text("tampered")
                elif mutation == "missing":
                    (self.assets / "SHA256SUMS").write_text("")
                else:
                    manifest = self.assets / "SHA256SUMS"
                    manifest.write_text(manifest.read_text() * 2)
                result = self.installer()
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("tool install", self.case.log.read_text())
                self.assertNotIn("Brig installed.", result.stderr)
                self.assertEqual(list(self.root.glob("brig-release.*")), [])

    def test_help_invalid_versions_and_root_never_download_release_assets(self):
        for arguments, status in (
            (("--help",), 0),
            (("--unknown",), 2),
            (("--version",), 2),
            (("--version", "main"), 2),
        ):
            result = self.installer(*arguments)
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertEqual(self.case.log.read_text(), "")
        result = self.installer(commands={"id": "echo 0"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("without sudo", result.stderr)
        self.assertEqual(self.case.log.read_text(), "")

    def test_download_or_install_failures_clean_up_without_reporting_success(self):
        for commands, message in (
            ({"curl": "echo 'offline' >&2; exit 22"}, "offline"),
            ({"uv": "echo 'install failed' >&2; exit 9"}, "install failed"),
            ({"sha256sum": None}, "requires sha256sum"),
            ({"curl": None, "wget": None}, "requires curl or wget"),
        ):
            result = self.installer(commands=commands)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertNotIn("Brig installed.", result.stderr)
            self.assertEqual(list(self.root.glob("brig-release.*")), [])
