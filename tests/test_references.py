"""Reference persistence, explicit lifecycle changes and agent discovery."""

import io
import json
import shlex
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from brig.components.agents import INSTRUCTIONS_FILE
from brig.docker.compose import compose_definition, render_compose
from brig.docker.isolation import agent_home, bootstrap_script
from brig.docker.services import agent_instructions
from brig.errors import BrigError
from brig.persistence.codec import SCHEMA_VERSION, decode_state
from brig.persistence.store import JsonStateStore
from brig.references import reference_mounts, reference_source, references_match
from brig.ui.cli import main
from brig.ui.presentation import project_lines
from tests import test_docker_engine


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.case = test_docker_engine.DockerEngineTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.app = self.case.app
        self.engine = self.case.engine
        self.runner = self.case.runner
        self.root = Path(self.case.folder.name)
        self.legacy = self.root / "legacy"
        self.legacy.mkdir()
        self.original = self.legacy / "auth.py"
        self.original.write_text("old login\n")

    @property
    def project(self):
        return self.app.project("api")

    def start(self):
        with redirect_stderr(io.StringIO()):
            return self.app.start("api")

    def apply(self):
        with redirect_stderr(io.StringIO()):
            return self.app.apply_references("api")

    def test_reference_is_persistent_metadata_without_copies_or_docker_calls(self):
        message = self.app.add_reference("api", self.legacy)
        self.assertIn("/references/legacy", message)
        self.assertEqual(self.project.references, {"legacy": str(self.legacy)})
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(list(Path(self.project.path).iterdir()), [])
        self.original.write_text("updated login\n")
        self.assertEqual(self.original.read_text(), "updated login\n")
        listing = self.app.list_references("api")
        self.assertIn(str(self.legacy), listing)
        self.assertIn("read-only", message)
        with redirect_stderr(io.StringIO()):
            self.app.stop("api")
        self.assertEqual(self.project.references, {"legacy": str(self.legacy)})
        self.assertTrue(self.original.exists())
        self.assertIn(
            "Reference  legacy",
            "\n".join(project_lines(self.app, self.project, status="stopped")),
        )

    def test_mount_is_read_only_and_only_in_work_container_without_image_changes(self):
        before = self.engine.workspace.plan(self.project, 1234, 4321)
        self.app.add_reference("api", self.legacy, "old-api")
        after = self.engine.workspace.plan(self.project, 1234, 4321)
        self.assertEqual(before, after)
        config = compose_definition(self.project, "image:test", 1234, 4321)
        reference = next(
            v
            for v in config["services"]["dev"]["volumes"]
            if isinstance(v, dict) and v.get("target") == "/references/old-api"
        )
        self.assertTrue(reference["read_only"])
        self.assertEqual(reference["bind"], {"create_host_path": False})
        self.assertEqual(reference["source"], str(self.legacy))
        for name, service in config["services"].items():
            if name != "dev":
                self.assertNotIn("/references/", str(service.get("volumes", [])))
        self.start()
        self.assertTrue(references_match(self.project, {"Mounts": self.runner.mounts}))
        self.start()  # Re-entering an unchanged environment remains supported.

    def test_running_changes_are_pending_until_explicit_work_container_recreation(self):
        self.start()
        self.runner.calls.clear()
        self.app.add_reference("api", self.legacy)
        self.assertEqual(self.runner.calls, [])
        with self.assertRaisesRegex(BrigError, "changes are pending"):
            self.start()
        self.assertFalse(
            any("up" in args or "down" in args for args, _ in self.runner.calls)
        )
        self.runner.calls.clear()
        self.assertIn("References applied", self.apply())
        up = next(args for args, _ in self.runner.calls if "up" in args)
        self.assertEqual(up[-3:], ["--no-deps", "--force-recreate", "dev"])
        self.assertIn("--no-build", up)
        self.assertFalse(
            any("build" in args or "down" in args for args, _ in self.runner.calls)
        )
        self.assertTrue(references_match(self.project, {"Mounts": self.runner.mounts}))
        self.start()
        self.app.remove_reference("api", "legacy")
        with self.assertRaisesRegex(BrigError, "changes are pending"):
            self.start()
        self.apply()
        self.assertTrue(references_match(self.project, {"Mounts": self.runner.mounts}))
        self.assertTrue(self.original.exists())

    def test_stopped_references_apply_with_start_and_failed_apply_keeps_configuration(
        self,
    ):
        self.app.add_reference("api", self.legacy)
        with self.assertRaisesRegex(BrigError, "Project is stopped"):
            self.apply()
        self.start()
        self.runner.failure = "up"
        with self.assertRaisesRegex(BrigError, "Docker failed"):
            self.apply()
        self.assertEqual(self.project.references, {"legacy": str(self.legacy)})
        self.assertTrue(self.original.exists())

    def test_failed_metadata_save_does_not_change_existing_configuration(self):
        self.case.store.fail = True
        with self.assertRaisesRegex(BrigError, "Disk is full"):
            self.app.add_reference("api", self.legacy)
        self.assertEqual(self.project.references, {})
        self.case.store.fail = False
        self.app.add_reference("api", self.legacy)
        self.case.store.fail = True
        with self.assertRaisesRegex(BrigError, "Disk is full"):
            self.app.remove_reference("api", "legacy")
        self.assertIn("legacy", self.project.references)
        self.assertEqual(self.runner.calls, [])

    def test_invalid_aliases_duplicates_missing_files_and_workspace_overlaps(self):
        self.assertIn("No references", self.app.list_references("api"))
        for alias in ("../escape", "", "Legacy", "a" * 65, "two words", 8):
            with (
                self.subTest(alias=alias),
                self.assertRaisesRegex(BrigError, "kebab-case"),
            ):
                self.app.add_reference("api", self.legacy, alias)
        for source in (self.root / "missing", self.original):
            with self.assertRaisesRegex(BrigError, "existing directory"):
                self.app.add_reference("api", source)
        child = Path(self.project.path) / "child"
        child.mkdir()
        for source in (self.root, Path(self.project.path), child):
            with self.assertRaisesRegex(BrigError, "outside"):
                self.app.add_reference("api", source)
        invalid = self.root / "bad\nfolder"
        invalid.mkdir()
        with self.assertRaisesRegex(BrigError, "existing directory"):
            self.app.add_reference("api", invalid, "valid-alias")
        self.app.add_reference("api", self.legacy)
        with self.assertRaisesRegex(BrigError, "already exists"):
            self.app.add_reference("api", self.legacy)
        with self.assertRaisesRegex(BrigError, "already a reference"):
            self.app.add_reference("api", self.legacy, "another")
        with self.assertRaisesRegex(BrigError, "Unknown reference"):
            self.app.remove_reference("api", "unknown")
        self.app.remove_reference("api", "legacy")
        self.assertEqual(self.project.references, {})

    def test_source_paths_resolve_symlinks_and_cannot_silently_change_destination(self):
        link = self.root / "alias"
        link.symlink_to(self.legacy, target_is_directory=True)
        self.app.add_reference("api", link)
        self.assertEqual(self.project.references, {"legacy": str(self.legacy)})
        other = self.root / "other"
        self.legacy.rename(other)
        self.legacy.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(BrigError, "changed its destination"):
            reference_mounts(self.project)
        self.legacy.unlink()
        with self.assertRaisesRegex(BrigError, "existing directory"):
            reference_mounts(self.project)
        # Missing original directories must not prevent unlinking their records.
        self.app.remove_reference("api", "legacy")

    def test_paths_with_spaces_and_dollars_are_explicit_and_compose_escaped(self):
        folder = self.root / "old app $example: code"
        folder.mkdir()
        with self.assertRaisesRegex(BrigError, "Use --as"):
            self.app.add_reference("api", folder)
        self.app.add_reference("api", folder, "legacy")
        self.assertIn(
            "$$example", render_compose(self.project, "image:test", 1234, 4321)
        )
        self.assertEqual(
            reference_source(type("Sample", (), {"path": None})(), folder), str(folder)
        )

    def test_malformed_reference_state_is_rejected_and_older_states_migrate(self):
        raw = {"schema_version": SCHEMA_VERSION, **asdict(self.app.state)}
        for references in (
            [],
            None,
            {"../escape": "/tmp"},
            {"legacy": "relative"},
            {"legacy": 7},
            {"legacy": "/bad\x00path"},
        ):
            modified = deepcopy(raw)
            modified["projects"][0]["references"] = references
            with (
                self.subTest(references=references),
                self.assertRaisesRegex(ValueError, "Invalid project references"),
            ):
                decode_state(modified)
        for version in (1, 2):
            modified = deepcopy(raw)
            modified["schema_version"] = version
            del modified["projects"][0]["references"]
            self.assertEqual(decode_state(modified).projects[0].references, {})
        self.app.add_reference("api", self.legacy)
        store = JsonStateStore(self.root / "data")
        store.save(self.app.state)
        self.assertEqual(store.load(), self.app.state)
        self.assertEqual(json.loads(store.path.read_text())["schema_version"], 3)

    def test_writable_or_extra_existing_mounts_cannot_silently_pass_pending_check(self):
        self.app.add_reference("api", self.legacy)
        mount = {
            "Destination": "/references/legacy",
            "Source": str(self.legacy),
            "RW": False,
        }
        self.assertTrue(references_match(self.project, {"Mounts": [mount]}))
        self.assertFalse(
            references_match(self.project, {"Mounts": [mount | {"RW": True}]})
        )
        self.assertFalse(
            references_match(
                self.project, {"Mounts": [mount | {"Source": "/elsewhere"}]}
            )
        )
        self.assertFalse(
            references_match(
                self.project,
                {"Mounts": [mount, mount | {"Destination": "/references/other"}]},
            )
        )

    def test_all_agents_receive_reference_guidance_and_runtime_mount_names(self):
        text = agent_instructions({})
        self.assertIn("/references/<alias>", text)
        self.assertIn("`/workspace` is the active project", text)
        self.assertIn("must not override", text)
        script = bootstrap_script(["claude", "codex", "opencode"])
        reference_root = self.root / "references"
        reference_root.mkdir()
        (reference_root / "legacy").mkdir()
        (reference_root / "not-a-project.txt").touch()
        for agent in ("claude", "codex", "opencode"):
            target = self.root / f"{agent}-instructions.md"
            home_path = f"{agent_home(agent)}/{INSTRUCTIONS_FILE}"
            base = f"printf '%s' {shlex.quote(text)} > {home_path}"
            self.assertIn(base, script)
            remainder = script[script.index(base) + len(base) :]
            loop = remainder[remainder.index("for reference in /references/*; do") :]
            loop = loop[: loop.index("\ndone") + len("\ndone")]
            loop = loop.replace(home_path, str(target))
            loop = loop.replace(
                "/references/*", shlex.quote(str(reference_root)) + "/*"
            )
            subprocess.run(
                ["sh", "-ec", base.replace(home_path, str(target)) + "\n" + loop],
                check=True,
            )
            notes = target.read_text()
            self.assertIn(text, notes)
            self.assertIn(
                f"Legacy reference (read-only): {reference_root}/legacy", notes
            )
            self.assertNotIn("not-a-project.txt", notes)

    def test_reference_cli_supports_explicit_project_auto_detection_list_remove_apply(
        self,
    ):
        store = JsonStateStore(self.root / "data")
        store.save(self.app.state)

        def cli(*arguments):
            output, errors = io.StringIO(), io.StringIO()
            with (
                patch("brig.ui.cli.DockerEngine", return_value=self.engine),
                patch("brig.ui.cli.Path.cwd", return_value=Path(self.project.path)),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                code = main(
                    ["--data-dir", str(store.path.parent), "reference", *arguments]
                )
            self.assertEqual(code, 0, errors.getvalue())
            return output.getvalue()

        self.assertIn("No references", cli("list"))
        self.assertIn(
            "/references/old-api",
            cli("add", str(self.legacy), "--project", "api", "--as", "old-api"),
        )
        self.assertIn("old-api", cli("list", "--project", "api"))
        with redirect_stderr(io.StringIO()):
            self.engine.start(store.load().projects[0])
        self.assertIn("References applied", cli("apply", "--project", "api"))
        self.assertIn(
            "Original files were kept", cli("remove", "old-api", "--project", "api")
        )
        self.assertIn("No references", cli("list"))
        self.assertTrue(self.original.exists())
