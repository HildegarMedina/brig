"""Attachment copies, isolation, cleanup and CLI behavior without Docker."""

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import chdir, redirect_stderr, redirect_stdout
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

    def attachment_command(self, directory, *arguments, command="attach"):
        output, errors = io.StringIO(), io.StringIO()
        with (
            chdir(directory),
            patch("brig.ui.cli.Application", return_value=self.app),
            redirect_stdout(output),
            redirect_stderr(errors),
            patch.object(self.app.engine, "start") as start,
        ):
            code = main([command, *arguments])
        start.assert_not_called()
        return code, output.getvalue(), errors.getvalue()

    def test_attach_detects_project_from_subfolder_and_resolves_relative_files(self):
        folder = self.folder / "src"
        folder.mkdir()
        second = self.root / "requirements.txt"
        second.write_text("project context")
        code, output, errors = self.attachment_command(
            folder, "../../design reference.png", "../../requirements.txt"
        )
        self.assertEqual(code, 0, errors)
        paths = output.splitlines()
        self.assertEqual(len(paths), 2)
        self.assertEqual(
            self.host_path(paths[0]).read_bytes(), self.source.read_bytes()
        )
        self.assertEqual(self.host_path(paths[1]).read_text(), "project context")
        self.assertEqual(errors, "")

    def test_attach_treats_all_positionals_as_files_even_when_named_after_project(self):
        source = self.folder / "api"
        source.write_text("a file, not a project selector")
        code, output, errors = self.attachment_command(self.folder, "api")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.host_path(output.strip()).read_text(), source.read_text())

    def test_attach_project_flag_overrides_current_folder_and_works_outside_projects(
        self,
    ):
        other = self.root / "other"
        other.mkdir()
        self.app.create_project("other", other, "python-dev")
        for directory in (self.folder, self.root):
            with self.subTest(directory=directory):
                code, output, errors = self.attachment_command(
                    directory, str(self.source), "--project", "other"
                )
                self.assertEqual(code, 0, errors)
                target = other / Path(output.strip()).relative_to("/workspace")
                self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertFalse((self.folder / ".brig").exists())

    def test_attach_selects_the_nearest_registered_project(self):
        nested = self.folder / "nested"
        nested.mkdir()
        self.app.create_project("inner", nested, "python-dev")
        code, output, errors = self.attachment_command(nested, str(self.source))
        self.assertEqual(code, 0, errors)
        target = nested / Path(output.strip()).relative_to("/workspace")
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertFalse((self.folder / ".brig").exists())

    def test_attach_outside_projects_requires_project_and_unknown_project_fails(self):
        for arguments, message in (
            ((str(self.source),), "No project found"),
            (("--project", "missing", str(self.source)), "Unknown project"),
        ):
            with self.subTest(arguments=arguments):
                code, output, errors = self.attachment_command(self.root, *arguments)
                self.assertEqual(code, 1)
                self.assertEqual(output, "")
                self.assertIn(message, errors)
        self.assertFalse((self.folder / ".brig").exists())

    def test_detach_and_alias_detect_project_without_removing_originals_or_context(
        self,
    ):
        subfolder = self.folder / "src"
        subfolder.mkdir()
        legacy = self.root / "legacy"
        legacy.mkdir()
        self.app.add_reference("api", legacy)
        for command in ("detach", "dettach"):
            for directory in (self.folder, subfolder):
                with self.subTest(command=command, directory=directory):
                    path = self.host_path(self.app.attach("api", [self.source]))
                    permanent = self.folder / ".brig/context/requirements.txt"
                    permanent.write_text("permanent context")
                    code, output, errors = self.attachment_command(
                        directory, command=command
                    )
                    self.assertEqual(code, 0, errors)
                    self.assertIn("Original files were kept", output)
                    self.assertFalse(path.exists())
                    self.assertEqual(permanent.read_text(), "permanent context")
                    self.assertEqual(self.source.read_bytes(), b"image reference")
                    self.assertEqual(
                        self.app.project("api").references, {"legacy": str(legacy)}
                    )
                    self.assertTrue(legacy.is_dir())
                    code, _, errors = self.attachment_command(
                        directory, command=command
                    )
                    self.assertEqual(code, 0, errors)

    def test_detach_project_flag_overrides_detection_and_works_outside_projects(self):
        other = self.root / "other"
        other.mkdir()
        self.app.create_project("other", other, "python-dev")
        api_copy = self.host_path(self.app.attach("api", [self.source]))
        for directory in (self.folder, self.root):
            with self.subTest(directory=directory):
                container_path = self.app.attach("other", [self.source])
                other_copy = other / Path(container_path).relative_to("/workspace")
                code, _, errors = self.attachment_command(
                    directory, "--project", "other", command="detach"
                )
                self.assertEqual(code, 0, errors)
                self.assertFalse(other_copy.exists())
                self.assertTrue(api_copy.exists())
                self.assertTrue(self.source.exists())

    def test_detach_uses_nearest_registered_project(self):
        nested = self.folder / "nested"
        nested.mkdir()
        self.app.create_project("inner", nested, "python-dev")
        child = nested / "src"
        child.mkdir()
        api_copy = self.host_path(self.app.attach("api", [self.source]))
        inner_path = self.app.attach("inner", [self.source])
        inner_copy = nested / Path(inner_path).relative_to("/workspace")
        code, _, errors = self.attachment_command(child, command="detach")
        self.assertEqual(code, 0, errors)
        self.assertFalse(inner_copy.exists())
        self.assertTrue(api_copy.exists())

    def test_detach_without_a_resolved_project_keeps_existing_attachments(self):
        path = self.host_path(self.app.attach("api", [self.source]))
        for command in ("detach", "dettach"):
            for arguments, message in (
                ((), "No project found"),
                (("--project", "missing"), "Unknown project"),
            ):
                with self.subTest(command=command, arguments=arguments):
                    code, output, errors = self.attachment_command(
                        self.root, *arguments, command=command
                    )
                    self.assertEqual(code, 1)
                    self.assertEqual(output, "")
                    self.assertIn(message, errors)
                    self.assertTrue(path.exists())
