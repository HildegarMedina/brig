"""Attachment copies, isolation, cleanup and CLI behavior without Docker."""

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from brig.application import Application
from brig.attachments import attach_files
from brig.errors import BrigError
from brig.models import State
from brig.ui.cli import main
from tests.demo_engine import DemoEngine
from tests.fakes import FakeVersionCatalog, MemoryStore


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root / "project"
        self.folder.mkdir()
        self.app = Application(MemoryStore(State()), DemoEngine(), FakeVersionCatalog)
        self.app.save_profile("python-dev", {"python": "3.12.8"}, {}, {})
        self.project = self.app.create_project("api", self.folder, "python-dev")
        self.source = self.root / "design reference.png"
        self.source.write_bytes(b"image reference")

    def host_path(self, container_path):
        return self.folder / Path(container_path).relative_to("/workspace")

    def test_attach_copies_bytes_and_keeps_colliding_names_separate(self):
        other = self.root / "other"
        other.mkdir()
        second = other / self.source.name
        second.write_bytes(b"other design")
        paths = self.app.attach("api", [self.source, second]).splitlines()
        self.assertEqual(len(paths), 2)
        self.assertNotEqual(paths[0], paths[1])
        self.assertEqual(self.host_path(paths[0]).read_bytes(), b"image reference")
        self.assertEqual(self.host_path(paths[1]).read_bytes(), b"other design")
        self.source.write_bytes(b"original changed")
        self.assertEqual(self.host_path(paths[0]).read_bytes(), b"image reference")
        self.assertFalse(self.project.running)
        self.assertEqual((self.folder / ".brig/context/.gitignore").read_text(), "*\n")
        self.app.attach("api", [self.source])

    def test_attachments_are_shared_with_the_agents_group(self):
        self.source.chmod(0o600)
        previous = os.umask(0o077)
        try:
            path = self.host_path(self.app.attach("api", [self.source]))
        finally:
            os.umask(previous)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o770)
        self.assertEqual(path.stat().st_mode & 0o777, 0o660)

    def test_generated_ignore_excludes_context_in_git(self):
        subprocess.run(["git", "init", "-q", str(self.folder)], check=True)
        path = self.host_path(self.app.attach("api", [self.source]))
        result = subprocess.run(
            ["git", "check-ignore", str(path)],
            cwd=self.folder,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_detach_is_idempotent_and_preserves_permanent_context_and_originals(self):
        path = self.host_path(self.app.attach("api", [self.source]))
        permanent = self.folder / ".brig/context/requirements.txt"
        permanent.write_text("permanent context")
        self.assertIn("Original files were kept", self.app.detach("api"))
        self.assertFalse(path.exists())
        self.assertTrue(self.source.exists())
        self.assertEqual(permanent.read_text(), "permanent context")
        self.app.detach("api")
        self.assertTrue(self.host_path(self.app.attach("api", [self.source])).exists())

    def test_project_stop_removes_copies_but_failed_stop_keeps_them(self):
        path = self.host_path(self.app.attach("api", [self.source]))
        self.app.start("api")
        with (
            patch.object(self.app.engine, "stop", side_effect=BrigError("failed")),
            self.assertRaisesRegex(BrigError, "failed"),
        ):
            self.app.stop("api")
        self.assertTrue(path.exists())
        self.assertTrue(self.app.project("api").running)
        self.app.stop("api")
        self.assertFalse(path.exists())
        self.assertFalse(self.app.project("api").running)

    def test_copies_are_isolated_between_projects(self):
        folder = self.root / "second-project"
        folder.mkdir()
        self.app.create_project("other", folder, "python-dev")
        self.app.attach("other", [self.source])
        self.app.attach("api", [self.source])
        self.app.detach("api")
        self.assertTrue(list((folder / ".brig/context/attachments").glob("*/")))

    def test_missing_files_and_directories_fail_before_copying(self):
        for files in ([], [self.source, self.root / "missing"], [self.root]):
            with self.subTest(files=files), self.assertRaises(BrigError):
                self.app.attach("api", files)
        self.assertFalse((self.folder / ".brig").exists())
        with self.assertRaisesRegex(BrigError, "Unknown project"):
            self.app.attach("unknown", [self.source])

    def test_missing_project_folder_reports_error_but_stop_remains_possible(self):
        self.folder.rmdir()
        with self.assertRaisesRegex(BrigError, "Project folder is missing"):
            self.app.attach("api", [self.source])
        self.assertIn("No attachments", self.app.detach("api"))
        self.app.stop("api")
        self.project.path = None
        with self.assertRaises(BrigError):
            attach_files(self.project, [self.source])
        self.assertIn("No attachments", self.app.detach("api"))

    def test_context_symlinks_and_non_directories_are_rejected(self):
        external = self.root / "external"
        external.mkdir()
        for name in (".brig", ".brig/context", ".brig/context/attachments"):
            destination = self.folder / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            for symlink in (True, False):
                if symlink:
                    destination.symlink_to(external, target_is_directory=True)
                else:
                    destination.write_text("keep")
                with self.subTest(name=name, symlink=symlink):
                    with self.assertRaisesRegex(BrigError, "real directory"):
                        self.app.attach("api", [self.source])
                    with self.assertRaises(BrigError):
                        self.app.detach("api")
                destination.unlink()
        self.assertEqual(list(external.iterdir()), [])

    def test_failed_copy_rolls_back_all_new_attachments(self):
        original_path = self.host_path(self.app.attach("api", [self.source]))
        with (
            patch("brig.attachments.shutil.copyfile", side_effect=OSError("disk full")),
            self.assertRaisesRegex(BrigError, "Cannot attach files"),
        ):
            self.app.attach("api", [self.source])
        self.assertEqual(
            list(original_path.parent.parent.iterdir()), [original_path.parent]
        )
        self.assertTrue(original_path.exists())

    def test_failed_directory_creation_and_removal_report_errors(self):
        with (
            patch("brig.attachments.Path.mkdir", side_effect=PermissionError("denied")),
            self.assertRaisesRegex(BrigError, "Cannot attach files"),
        ):
            self.app.attach("api", [self.source])
        self.app.attach("api", [self.source])
        with (
            patch(
                "brig.attachments.shutil.rmtree", side_effect=PermissionError("denied")
            ),
            self.assertRaisesRegex(BrigError, "Cannot remove attachments"),
        ):
            self.app.detach("api")

    def test_cli_attach_and_detach_print_paths_without_starting_an_agent(self):
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch("brig.ui.cli.Application", return_value=self.app),
            redirect_stdout(output),
            redirect_stderr(errors),
            patch.object(self.app.engine, "start") as start,
        ):
            self.assertEqual(main(["project", "attach", "api", str(self.source)]), 0)
            path = self.host_path(output.getvalue().strip())
            self.assertTrue(path.exists())
            self.assertEqual(main(["project", "detach", "api"]), 0)
            self.assertFalse(path.exists())
            self.assertEqual(main(["project", "attach", "api", str(self.root)]), 1)
            start.assert_not_called()
        self.assertIn("regular file", errors.getvalue())
