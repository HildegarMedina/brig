"""Persistence round-trip, corruption handling, and atomic failure tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from brig.application import Application, demo_state
from brig.engine import DemoEngine
from brig.errors import BrigError
from brig.storage import JsonStateStore, default_data_directory


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = JsonStateStore(Path(self.directory.name) / "data")

    def test_missing_state_returns_none(self):
        self.assertIsNone(self.store.load())

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
