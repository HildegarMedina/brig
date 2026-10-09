"""Persistence round-trip, corruption handling, and atomic failure tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brig.application import Application
from brig.engine import DemoEngine
from brig.errors import BrigError
from brig.storage import JsonStateStore, default_data_directory
from brig.profile_yaml import profile_path, render_profile
from brig.models import Profile, ProfileRevision
from tests.fakes import demo_state, FakeVersionCatalog


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = JsonStateStore(Path(self.directory.name) / "data")

    def test_missing_state_returns_none(self):
        self.assertIsNone(self.store.load())

    def test_deleting_profile_removes_all_yaml_revisions_and_allows_recreation(self):
        app = Application(self.store, DemoEngine(), FakeVersionCatalog)
        app.save_profile("custom", {"php": "8.3.15"}, {}, {})
        app.save_profile("custom", {"php": "8.2.27"}, {}, {}, editing=True)
        directory = profile_path(self.store.path.parent, "custom", 1).parent
        self.assertEqual(len(list(directory.glob("*.yaml"))), 2)
        app.delete_profile("custom")
        self.assertFalse(directory.exists())
        self.assertEqual(self.store.load(), app.state)
        self.assertEqual(list(self.store.path.parent.glob(".delete-profile-*")), [])
        app.save_profile("custom", {"python": "3.12.8"}, {}, {})
        self.assertIn(
            'python: "3.12.8"',
            profile_path(self.store.path.parent, "custom", 1).read_text(),
        )

    def test_failed_delete_restores_yaml_directory_and_original_state(self):
        app = Application(self.store, DemoEngine(), FakeVersionCatalog)
        app.save_profile("custom", {"php": "8.3.15"}, {}, {})
        app.save_profile("custom", {"php": "8.2.27"}, {}, {}, editing=True)
        original = self.store.path.read_bytes()
        directory = profile_path(self.store.path.parent, "custom", 1).parent
        documents = {path.name: path.read_bytes() for path in directory.iterdir()}
        import os

        replace = os.replace

        def fail_state(source, destination):
            if destination == self.store.path:
                raise OSError("state failed")
            replace(source, destination)

        with (
            patch("brig.storage.os.replace", side_effect=fail_state),
            self.assertRaisesRegex(BrigError, "Cannot save"),
        ):
            app.delete_profile("custom")
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(
            {path.name: path.read_bytes() for path in directory.iterdir()}, documents
        )
        self.assertEqual(self.store.load(), app.state)
        self.assertEqual(list(self.store.path.parent.glob(".delete-profile-*")), [])

    def test_failed_restore_preserves_original_yaml_in_staging_directory(self):
        app = Application(self.store, DemoEngine(), FakeVersionCatalog)
        app.save_profile("custom", {"php": "8.3.15"}, {}, {})
        original = self.store.path.read_bytes()
        document = profile_path(self.store.path.parent, "custom", 1)
        contents = document.read_bytes()
        import os

        replace = os.replace

        def fail_state_and_restore(source, destination):
            if destination in (self.store.path, document.parent):
                raise OSError("write failure")
            replace(source, destination)

        with (
            patch("brig.storage.os.replace", side_effect=fail_state_and_restore),
            self.assertRaisesRegex(BrigError, "Original YAML files are preserved"),
        ):
            app.delete_profile("custom")
        self.assertEqual(self.store.path.read_bytes(), original)
        staged = list(
            self.store.path.parent.glob(".delete-profile-*/revisions/revision-1.yaml")
        )
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].read_bytes(), contents)

    def test_round_trip_includes_revisions_and_project_snapshots(self):
        state = demo_state()
        self.store.save(state)
        self.assertEqual(self.store.load(), state)
        app = Application(self.store, DemoEngine())
        app.start("website")
        reloaded = Application(self.store, DemoEngine())
        self.assertTrue(reloaded.project("website").running)

    def test_corrupt_data_is_not_overwritten(self):
        cases = ["{broken", "null", "[]", '{"schema_version": 900}']
        self.store.path.parent.mkdir()
        for contents in cases:
            with self.subTest(contents=contents):
                self.store.path.write_text(contents)
                with self.assertRaisesRegex(BrigError, "File was not changed"):
                    Application(self.store, DemoEngine())
                self.assertEqual(self.store.path.read_text(), contents)

    def test_invalid_relationships_and_types_are_rejected(self):
        self.store.save(demo_state())
        original = self.store.path.read_text()
        for mutate in (
            lambda data: data.update(profiles=""),
            lambda data: data["projects"][0].update(name="bad\x1bname"),
            lambda data: data["projects"][0].update(profile="unknown"),
            lambda data: data["projects"][0].update(running="yes"),
            lambda data: data["profiles"][0].update(revisions=[]),
            lambda data: data["projects"][0]["configuration"].update(number=99),
            lambda data: data["projects"][0].update(path="relative/path"),
            lambda data: data["profiles"][0]["revisions"][0].update(
                runtimes={"php": "latest"}
            ),
        ):
            data = json.loads(original)
            mutate(data)
            contents = json.dumps(data)
            self.store.path.write_text(contents)
            with self.subTest(data=data), self.assertRaises(BrigError):
                self.store.load()
            self.assertEqual(self.store.path.read_text(), contents)

    def test_non_utf8_data_is_reported_without_overwriting(self):
        self.store.path.parent.mkdir()
        self.store.path.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(BrigError, "File was not changed"):
            Application(self.store, DemoEngine())
        self.assertEqual(self.store.path.read_bytes(), b"\xff\xfe")

    def test_failed_replace_preserves_previous_file_and_removes_temporary_file(self):
        state = demo_state()
        self.store.save(state)
        original = self.store.path.read_bytes()
        state.projects[0].running = True
        with patch("brig.storage.os.replace", side_effect=OSError("write failure")):
            with self.assertRaisesRegex(BrigError, "Cannot save"):
                self.store.save(state)
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.store.path.parent.glob(".state-*.tmp")), [])

    def test_xdg_data_directory(self):
        with patch.dict("os.environ", {"XDG_DATA_HOME": "/tmp/brig-unit-data"}):
            self.assertEqual(default_data_directory(), Path("/tmp/brig-unit-data/brig"))

    def test_profile_creation_produces_readable_yaml_and_keeps_previous_revision(self):
        app = Application(self.store, DemoEngine(), FakeVersionCatalog)
        app.save_profile(
            "custom",
            {"node": "22.13.1"},
            {"pnpm": "9.15.0"},
            {"mysql": "8.4.3", "redis": "7.4.2"},
        )
        document = profile_path(self.store.path.parent, "custom", 1)
        contents = document.read_text()
        self.assertIn('runtimes:\n  node: "22.13.1"', contents)
        self.assertIn('databases:\n  mysql: "8.4.3"', contents)
        self.assertIn('caches:\n  redis: "7.4.2"', contents)
        app.save_profile("custom", {"node": "20.18.2"}, {}, {}, editing=True)
        self.assertEqual(document.read_text(), contents)
        self.assertTrue(profile_path(self.store.path.parent, "custom", 2).exists())

    def test_loading_pinned_release_does_not_contact_version_sources(self):
        state = demo_state()
        state.profiles.append(
            Profile("future", [ProfileRevision(1, {"python": "3.99.1"}, {}, {})])
        )
        self.store.save(state)
        with patch(
            "brig.versions.urlopen", side_effect=AssertionError("network forbidden")
        ):
            self.assertEqual(self.store.load(), state)

    def test_failed_state_commit_removes_new_yaml_revision(self):
        state = demo_state()
        self.store.save(state)
        original = self.store.path.read_bytes()
        state.profiles[0].revisions.append(
            ProfileRevision(2, {"php": "8.3.15"}, {}, {})
        )
        import os

        replace = os.replace

        def fail_state(source, destination):
            if destination == self.store.path:
                raise OSError("state failed")
            replace(source, destination)

        with (
            patch("brig.storage.os.replace", side_effect=fail_state),
            self.assertRaises(BrigError),
        ):
            self.store.save(state)
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertFalse(profile_path(self.store.path.parent, "web-dev", 2).exists())
        self.assertEqual(list(self.store.path.parent.rglob("*.tmp")), [])

    def test_yaml_quotes_names_and_cannot_escape_profile_directory(self):
        name = '../../bad: "name"'
        path = profile_path(self.store.path.parent, name, 1)
        self.assertTrue(path.is_relative_to(self.store.path.parent / "profiles"))
        contents = render_profile(name, ProfileRevision(1, {"php": "8.3.15"}, {}, {}))
        self.assertIn('name: "../../bad: \\"name\\""', contents)
        self.assertIn("tools: {}", contents)
