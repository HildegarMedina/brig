"""Portable profile imports validate whole batches and preserve saved state."""

import io
import json
import os
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from brig.application import Application
from brig.errors import BrigError
from brig.models import Profile, ProfileParent, ProfileVersion, State
from brig.persistence.profile_reader import read_profile, read_profiles
from brig.persistence.profile_yaml import profile_path, render_profile
from brig.persistence.store import JsonStateStore
from brig.profiles.importing import merge_profiles
from brig.ui.cli import main
from tests.fakes import MemoryStore, demo_state


class ProfileImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.version = ProfileVersion(
            1,
            {"python": "3.12.8"},
            {"uv": "0.5.24"},
            {"postgresql": "17.2", "redis": "7.4.2"},
            "codex",
            ["codex"],
        )
        self.store = MemoryStore(State())
        self.engine = Mock()
        self.catalog = Mock(side_effect=AssertionError("Import must work offline"))
        self.app = Application(self.store, self.engine, self.catalog)

    def document(self, name="base", version=None, filename=None):
        path = self.root / (filename or f"{name}.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_profile(name, version or self.version), encoding="utf-8")
        return path

    def test_writer_reader_roundtrip_and_legacy_single_agent(self):
        self.assertEqual(read_profile(self.document()), Profile("base", [self.version]))
        legacy = replace(self.version, agents=None)
        path = self.document(version=legacy)
        text = path.read_text().replace("schema_version: 2", "schema_version: 1")
        path.write_text(text.replace("\nversion: 1\n", "\nrevision: 1\n"))
        self.assertEqual(read_profile(path), Profile("base", [legacy]))

    def test_read_multiple_files_and_nested_folder_ignores_other_files(self):
        first = self.document(filename="nested/base.YML")
        second = self.document("other", filename="other.yaml")
        self.document("ignored", filename="ignored.txt")
        (self.root / "directory.yaml").mkdir()
        self.assertEqual(len(read_profiles([self.root])), 2)
        self.assertEqual(len(read_profiles([first, second])), 2)

    def test_invalid_yaml_and_profile_fields_are_rejected(self):
        path = self.document()
        valid = path.read_text()
        invalid = [
            "[]",
            "",
            "schema_version: [",
            valid + "---\n{}\n",
            valid.replace("schema_version: 2", "schema_version: true"),
            valid.replace("schema_version: 2", "schema_version: 3"),
            valid.replace('name: "base"', 'name: ""'),
            valid.replace("version: 1\n", "version: true\n"),
            valid.replace("version: 1\n", ""),
            valid + "unknown: value\n",
            valid.replace('python: "3.12.8"', "python: 3.12"),
            valid.replace('python: "3.12.8"', 'unknown: "3.12.8"'),
            valid.replace('agent: "codex"', 'agent: "unknown"'),
            valid.replace("databases:\n", "databases: []\nremoved:\n"),
            valid.replace('postgresql: "17.2"', 'redis: "7.4.2"'),
            valid.replace('redis: "7.4.2"', 'postgresql: "17.2"'),
            valid.replace('redis: "7.4.2"', 'unknown: "7.4.2"'),
            valid + 'name: "duplicate"\n',
            valid.replace('python: "3.12.8"', 'python: "3.12.8"\n  python: "3.11.11"'),
            valid.replace('name: "base"', '42: "base"'),
            valid.replace('name: "base"', 'name: &value "base"') + "unknown: *value\n",
            valid.replace(
                'name: "base"', 'name: !!python/object/apply:os.system ["false"]'
            ),
            valid + "extends: {profile: base, version: false}\n",
        ]
        # Test a malformed section without an unrelated unknown-field error.
        invalid.append(
            valid.replace('databases:\n  postgresql: "17.2"', "databases: []")
        )
        for contents in invalid:
            with self.subTest(contents=contents), self.assertRaises(BrigError):
                path.write_text(contents)
                self.app.import_profiles([path])
        self.assertEqual(self.app.state, State())
        self.assertEqual(self.store.state, State())

    def test_read_errors_encoding_and_size_limits(self):
        with self.assertRaisesRegex(BrigError, "Cannot read profile"):
            read_profile(self.root / "missing.yaml")
        path = self.document()
        path.write_bytes(b"\xff")
        with self.assertRaisesRegex(BrigError, "Invalid profile YAML"):
            read_profile(path)
        with patch("brig.persistence.profile_reader.MAX_DOCUMENT_BYTES", 16):
            path.write_bytes(b"x" * 17)
            with self.assertRaisesRegex(BrigError, "size limit"):
                read_profile(path)

    def test_empty_input_empty_folder_and_scan_error(self):
        with self.assertRaisesRegex(BrigError, "at least one"):
            read_profiles([])
        with self.assertRaisesRegex(BrigError, "No profile YAML"):
            read_profiles([self.root])
        with (
            patch.object(Path, "rglob", side_effect=PermissionError("denied")),
            self.assertRaisesRegex(BrigError, "Cannot scan"),
        ):
            read_profiles([self.root])

    def test_full_history_and_inheritance_are_sorted_and_imported_offline(self):
        base = self.document("z-base", filename="history/base-1.yaml")
        latest = replace(self.version, number=2, runtimes={"python": "3.11.11"})
        base2 = self.document("z-base", latest, "history/base-2.yaml")
        child_version = replace(latest, number=1, extends=ProfileParent("z-base", 2))
        child = self.document("a-child", child_version)
        result = self.app.import_profiles([child, base2, base])
        self.assertIn("Imported 3", result)
        self.assertEqual(self.app.profile("z-base").versions, [self.version, latest])
        self.assertEqual(self.app.profile("a-child").latest, child_version)
        self.catalog.assert_not_called()
        self.assertEqual(self.engine.mock_calls, [])
        with self.assertRaisesRegex(BrigError, "Inherited by"):
            self.app.delete_profile("z-base")

    def test_existing_base_supports_importing_only_child_and_chain(self):
        self.app.import_profiles([self.document()])
        child_version = replace(self.version, extends=ProfileParent("base", 1))
        child = self.document("child", child_version)
        grandchild = self.document(
            "grandchild", replace(self.version, extends=ProfileParent("child", 1))
        )
        self.app.import_profiles([grandchild, child])
        self.assertEqual(len(self.app.state.profiles), 3)

    def test_invalid_inheritance_never_partially_imports(self):
        original = deepcopy(self.app.state)
        base = self.document()
        cases = [
            replace(self.version, extends=ProfileParent("missing", 1)),
            replace(self.version, extends=ProfileParent("base", 9)),
            replace(self.version, extends=ProfileParent("child", 1)),
            replace(self.version, tools={}, extends=ProfileParent("base", 1)),
            replace(
                self.version,
                agents=["claude"],
                agent="claude",
                extends=ProfileParent("base", 1),
            ),
        ]
        for version in cases:
            with self.subTest(version=version), self.assertRaises(BrigError):
                self.app.import_profiles([base, self.document("child", version)])
            self.assertEqual(self.app.state, original)
            self.assertEqual(self.store.state, original)
        cyclic_base = self.document(
            version=replace(self.version, extends=ProfileParent("child", 1))
        )
        child = self.document(
            "child", replace(self.version, extends=ProfileParent("base", 1))
        )
        with self.assertRaisesRegex(BrigError, "cycles"):
            self.app.import_profiles([cyclic_base, child])

    def test_idempotency_skips_save_and_rejects_conflicting_existing_version(self):
        path = self.document()
        self.app.import_profiles([path])
        original = deepcopy(self.app.state)
        self.store.fail = True
        self.assertIn(
            "0 profile versions; 2 already present",
            self.app.import_profiles([path, path]),
        )
        different = self.document(version=replace(self.version, tools={}))
        with self.assertRaisesRegex(BrigError, "different configuration"):
            self.app.import_profiles([different])
        with self.assertRaisesRegex(BrigError, "conflicts"):
            self.app.import_profiles([self.document("BASE")])
        self.assertEqual(self.app.state, original)

    def test_conflicting_documents_and_history_gaps_reject_whole_batch(self):
        first = self.document()
        conflict = self.document(
            version=replace(self.version, tools={}), filename="different.yaml"
        )
        with self.assertRaisesRegex(BrigError, "different configuration"):
            self.app.import_profiles([first, conflict])
        gap = self.document("gap", replace(self.version, number=2))
        with self.assertRaisesRegex(BrigError, "Missing version 1"):
            self.app.import_profiles([first, gap])
        self.assertEqual(self.app.state, State())

    def test_append_version_preserves_projects_and_existing_history(self):
        state = demo_state()
        app = Application(MemoryStore(state), self.engine, self.catalog)
        version = replace(state.profiles[1].latest, number=3, tools={})
        app.import_profiles([self.document("python_dev", version)])
        self.assertEqual(app.state.projects, state.projects)
        self.assertEqual(
            app.profile("python_dev").versions[:2], state.profiles[1].versions
        )
        self.assertEqual(app.profile("python_dev").latest, version)

    def test_save_failure_preserves_application_state(self):
        self.store.fail = True
        with self.assertRaisesRegex(BrigError, "Disk is full"):
            self.app.import_profiles([self.document()])
        self.assertEqual(self.app.state, State())
        self.assertEqual(self.store.state, State())

    def test_disk_transaction_rolls_back_all_new_documents(self):
        store = JsonStateStore(self.root / "data")
        app = Application(store, self.engine, self.catalog)
        store.save(app.state)
        before = store.path.read_bytes()
        replace_file = os.replace

        def fail_state(source, target):
            if Path(target) == store.path:
                raise OSError("disk failure")
            return replace_file(source, target)

        with (
            patch("brig.persistence.store.os.replace", side_effect=fail_state),
            self.assertRaisesRegex(BrigError, "disk failure"),
        ):
            app.import_profiles([self.document(), self.document("other")])
        self.assertEqual(store.path.read_bytes(), before)
        self.assertEqual(list(store.path.parent.rglob("*.yaml")), [])
        self.assertEqual(app.state, State())

    def test_cli_import_persists_yaml_and_reports_errors_without_terminal(self):
        data = self.root / "data"
        path = self.document()
        with (
            patch("brig.ui.cli.DockerEngine") as engine,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            self.assertEqual(
                main(["--data-dir", str(data), "profile", "import", str(path)]), 0
            )
            self.assertIn("Imported 1", output.getvalue())
            self.assertEqual(engine.return_value.mock_calls, [])
        self.assertEqual(
            JsonStateStore(data).load().profiles, [Profile("base", [self.version])]
        )
        self.assertEqual(
            read_profile(profile_path(data, "base", 1)), read_profile(path)
        )
        with patch("sys.stderr", new_callable=io.StringIO) as errors:
            self.assertEqual(
                main(
                    [
                        "--data-dir",
                        str(data),
                        "profile",
                        "import",
                        str(self.root / "missing"),
                    ]
                ),
                1,
            )
            self.assertIn("Cannot read profile", errors.getvalue())
        self.assertEqual(
            json.loads((data / "state.json").read_text())["schema_version"], 2
        )

    def test_merge_revalidates_existing_state(self):
        invalid = State([Profile("base", [replace(self.version, number=2)])])
        with self.assertRaisesRegex(BrigError, "Cannot import profiles"):
            merge_profiles(invalid, [])
