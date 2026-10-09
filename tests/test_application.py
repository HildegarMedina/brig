"""Behavior tests for application use cases, without terminal dependencies."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from brig.application import Application
from brig.engine import DemoEngine
from brig.errors import BrigError
from brig.models import State
from tests.fakes import MemoryStore, FakeVersionCatalog


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = MemoryStore(State())
        self.app = Application(self.store, DemoEngine(), FakeVersionCatalog)
        self.app.save_profile("python", {"python": "3.11.11"}, {"uv": "0.5.24"}, {})

    def create_project(self, name="first"):
        folder = self.root / name
        folder.mkdir()
        return self.app.create_project(name, folder, "python")

    def test_existing_empty_state_is_not_reseeded(self):
        app = Application(MemoryStore(State()), DemoEngine())
        self.assertEqual(app.state.projects, [])
        self.assertEqual(app.state.profiles, [])

    def test_first_run_seeds_examples_with_no_host_mounts(self):
        store = MemoryStore()
        app = Application(store, DemoEngine())
        self.assertEqual(len(app.state.projects), 2)
        self.assertTrue(all(p.path is None for p in app.state.projects))
        self.assertIsNotNone(store.state)

    def test_projects_have_independent_snapshots_resources_and_status(self):
        first = self.create_project("first")
        second = self.create_project("second")
        first_env = self.app.engine.describe(first)
        second_env = self.app.engine.describe(second)
        self.assertNotEqual(first_env.development, second_env.development)
        self.assertNotEqual(first_env.network, second_env.network)
        self.assertTrue(set(first_env.volumes).isdisjoint(second_env.volumes))
        self.assertIsNot(first.configuration, second.configuration)
        self.assertIsNot(first.configuration.runtimes, second.configuration.runtimes)
        self.app.start("first")
        self.assertTrue(self.app.project("first").running)
        self.assertFalse(self.app.project("second").running)

    def test_profile_edit_requires_explicit_project_update(self):
        self.create_project("first")
        self.create_project("second")
        self.app.save_profile(
            "python", {"python": "3.12.8"}, {}, {"redis": "7.4.2"}, editing=True
        )
        self.assertEqual(self.app.project("first").configuration.number, 1)
        self.assertEqual(self.app.project("second").configuration.number, 1)
        self.app.update_project("first")
        self.assertEqual(
            self.app.project("first").configuration.runtimes, {"python": "3.12.8"}
        )
        self.assertEqual(self.app.project("first").configuration.number, 2)
        self.assertEqual(self.app.project("second").configuration.number, 1)
        self.assertIn("already", self.app.update_project("first"))

    def test_running_project_cannot_apply_update(self):
        self.create_project()
        self.app.start("first")
        self.app.save_profile("python", {"python": "3.12.8"}, {}, {}, editing=True)
        with self.assertRaisesRegex(BrigError, "Stop"):
            self.app.update_project("first")
        self.assertEqual(self.app.project("first").configuration.number, 1)
        self.app.stop("first")
        self.app.update_project("first")
        self.assertEqual(self.app.project("first").configuration.number, 2)

    def test_duplicate_names_are_case_insensitive(self):
        with self.assertRaisesRegex(BrigError, "already exists"):
            self.app.save_profile("PYTHON", {"python": "3.12.8"}, {}, {})
        self.create_project()
        with self.assertRaisesRegex(BrigError, "already exists"):
            self.app.create_project("FIRST", self.root, "python")

    def test_missing_folder_and_duplicate_folder_are_rejected(self):
        with self.assertRaisesRegex(BrigError, "does not exist"):
            self.app.create_project("missing", self.root / "absent", "python")
        project = self.create_project()
        with self.assertRaisesRegex(BrigError, "already registered"):
            self.app.create_project("other", Path(project.path), "python")

    def test_project_detection_uses_nearest_registered_parent(self):
        project = self.create_project("parent")
        nested = Path(project.path) / "child"
        nested.mkdir()
        child = self.app.create_project("child", nested, "python")
        self.assertEqual(self.app.resolve_project(None, nested / "src").id, child.id)
        self.assertEqual(self.app.resolve_project("parent", nested).id, project.id)
        with self.assertRaisesRegex(BrigError, "--project"):
            self.app.resolve_project(None, self.root)

    def test_invalid_catalog_selections_do_not_save(self):
        cases = [
            ({}, {}, {}, "claude"),
            ({"python": "latest"}, {}, {}, "claude"),
            ({"python": "3.12.8"}, {"composer": "2.8.5"}, {}, "claude"),
            ({"python": "3.12.8"}, {}, {"mysql": "8"}, "claude"),
            ({"python": "3.12.8"}, {}, {}, "codex"),
        ]
        for runtimes, tools, services, agent in cases:
            with self.subTest(
                runtimes=runtimes, tools=tools, services=services, agent=agent
            ):
                with self.assertRaises(BrigError):
                    self.app.save_profile("invalid", runtimes, tools, services, agent)
                self.assertEqual(len(self.app.state.profiles), 1)

    def test_failed_save_does_not_change_in_memory_state(self):
        self.create_project()
        before = deepcopy(self.app.state)
        self.store.fail = True
        with self.assertRaisesRegex(BrigError, "Disk is full"):
            self.app.start("first")
        self.assertEqual(self.app.state, before)

    def test_new_release_is_accepted_without_changing_catalog_definitions(self):
        self.app.save_profile(
            "future",
            {"python": "3.99.1"},
            {},
            {},
            catalog=FakeVersionCatalog({"python": ("3.99.1",)}),
        )
        self.assertEqual(
            self.app.profile("future").latest.runtimes, {"python": "3.99.1"}
        )

    def test_nonexistent_release_is_rejected_before_persistence(self):
        before = deepcopy(self.app.state)
        with self.assertRaisesRegex(BrigError, "not available"):
            self.app.save_profile("invalid", {"python": "3.99.1"}, {}, {})
        self.assertEqual(self.app.state, before)

    def test_demo_agent_and_shell_require_running_project(self):
        self.create_project()
        with self.assertRaisesRegex(BrigError, "stopped"):
            self.app.run_agent("first", "claude")
        with self.assertRaisesRegex(BrigError, "stopped"):
            self.app.shell("first")
        self.app.start("first")
        self.assertIn("no agent was launched", self.app.run_agent("first", "claude"))
        self.assertIn("no shell was opened", self.app.shell("first"))
        with self.assertRaisesRegex(BrigError, "future integration"):
            self.app.run_agent("first", "opencode")
        with self.assertRaisesRegex(BrigError, "Unknown agent"):
            self.app.run_agent("first", "unknown")

    def test_start_and_stop_are_idempotent(self):
        self.create_project()
        self.app.start("first")
        self.assertIn("already running", self.app.start("first"))
        self.app.stop("first")
        self.assertIn("already stopped", self.app.stop("first"))

    def test_name_validation(self):
        for name in ("", "  ", "x" * 65, "bad\nname", "bad\x1bname"):
            with self.subTest(name=name), self.assertRaises(BrigError):
                self.app.save_profile(name, {"python": "3.12.8"}, {}, {})
