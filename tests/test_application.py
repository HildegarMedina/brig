"""Behavior tests for application use cases, without terminal dependencies."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from brig.application import Application
from brig.engine import DemoEngine
from brig.errors import BrigError
from brig.models import State
from tests.fakes import MemoryStore, FakeVersionCatalog, demo_state


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

    def test_delete_project_keeps_local_files_and_profile(self):
        project = self.create_project()
        source = Path(project.path) / "app.py"
        source.write_text("print('hello')\n")
        profile = deepcopy(self.app.profile("python"))
        self.assertIn("Deleted project 'first'", self.app.delete_project("first"))
        self.assertEqual(self.app.state.projects, [])
        self.assertEqual(self.store.load().projects, [])
        self.assertEqual(source.read_text(), "print('hello')\n")
        self.assertEqual(self.app.profile("python"), profile)
        self.app.create_project("first", Path(project.path), "python")

    def test_running_project_must_be_stopped_before_deletion(self):
        self.create_project()
        self.app.start("first")
        before = deepcopy(self.app.state)
        with self.assertRaisesRegex(BrigError, "brig down --project first"):
            self.app.delete_project("first")
        self.assertEqual(self.app.state, before)
        self.app.stop("first")
        self.app.delete_project("first")
        self.assertEqual(self.app.state.projects, [])

    def test_failed_project_deletion_preserves_state(self):
        self.create_project()
        before = deepcopy(self.app.state)
        self.store.fail = True
        with self.assertRaisesRegex(BrigError, "Disk is full"):
            self.app.delete_project("first")
        self.assertEqual(self.app.state, before)
        self.assertEqual(self.store.load(), before)

    def test_unknown_project_cannot_be_deleted(self):
        before = deepcopy(self.app.state)
        with self.assertRaisesRegex(BrigError, "Unknown project"):
            self.app.delete_project("missing")
        self.assertEqual(self.app.state, before)

    def test_delete_unused_profile_and_reuse_its_name(self):
        message = self.app.delete_profile("PYTHON")
        self.assertIn("Deleted profile 'python'", message)
        self.assertEqual(self.app.state.profiles, [])
        self.assertEqual(self.store.load().profiles, [])
        self.app.save_profile("python", {"python": "3.12.8"}, {}, {})
        self.assertEqual(self.app.profile("python").latest.number, 1)

    def test_cannot_delete_profile_used_by_stopped_or_running_projects(self):
        self.create_project("first")
        self.create_project("second")
        self.app.start("second")
        before = deepcopy(self.app.state)
        with self.assertRaisesRegex(BrigError, "Used by projects: first, second"):
            self.app.delete_profile("python")
        self.assertEqual(self.app.state, before)

    def test_failed_profile_delete_preserves_memory_and_persisted_state(self):
        before = deepcopy(self.app.state)
        self.store.fail = True
        with self.assertRaisesRegex(BrigError, "Disk is full"):
            self.app.delete_profile("python")
        self.assertEqual(self.app.state, before)
        self.assertEqual(self.store.load(), before)

    def test_unknown_profile_cannot_be_deleted(self):
        before = deepcopy(self.app.state)
        with self.assertRaisesRegex(BrigError, "Unknown profile"):
            self.app.delete_profile("missing")
        self.assertEqual(self.app.state, before)

    def test_first_run_starts_and_persists_empty_lists(self):
        store = MemoryStore()
        app = Application(store, DemoEngine())
        self.assertEqual(app.state, State())
        self.assertEqual(store.state, State())

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

    def test_duplicate_names_are_rejected(self):
        with self.assertRaisesRegex(BrigError, "already exists"):
            self.app.save_profile("python", {"python": "3.12.8"}, {}, {})
        self.create_project()
        with self.assertRaisesRegex(BrigError, "already exists"):
            self.app.create_project("first", self.root, "python")

    def test_duplicate_profile_is_rejected_before_fetching_versions(self):
        from unittest.mock import Mock

        self.app.catalog_factory = Mock(
            side_effect=AssertionError("No version lookup should occur")
        )
        with self.assertRaisesRegex(BrigError, "already exists.*Choose another name"):
            self.app.save_profile(" python ", {"python": "3.12.8"}, {}, {})
        self.app.catalog_factory.assert_not_called()

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
            ({"python": "3.12.8"}, {}, {}, "unknown"),
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

    def test_incompatible_tool_is_rejected_before_persistence(self):
        import json
        from brig.versions import LiveVersionCatalog

        before = deepcopy(self.app.state)
        payload = {"stable": [{"version": "2.10.3", "min-php": 80400}]}
        catalog = LiveVersionCatalog(
            lambda url: (
                json.dumps(payload)
                if url == "https://getcomposer.org/versions"
                else "Tags: 8.3.15\nArchitectures: amd64"
            )
        )
        with self.assertRaisesRegex(BrigError, "PHP 8.3.15.*Requires: >=8.4.0"):
            self.app.save_profile(
                "invalid",
                {"php": "8.3.15"},
                {"composer": "2.10.3"},
                {},
                catalog=catalog,
            )
        self.assertEqual(self.app.state, before)

    def test_demo_agent_and_shell_start_project(self):
        self.create_project()
        self.assertIn("no agent was launched", self.app.run_agent("first", "claude"))
        self.assertTrue(self.app.project("first").running)
        self.assertIn("no shell was opened", self.app.shell("first"))
        self.app.start("first")
        self.assertIn("no agent was launched", self.app.run_agent("first", "claude"))
        self.assertIn("no shell was opened", self.app.shell("first"))
        with self.assertRaisesRegex(BrigError, "not selected"):
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
        for name in (
            "",
            "  ",
            "x" * 65,
            "bad\nname",
            "bad\x1bname",
            "Laravel Project",
            "Uppercase",
            "foo_bar",
            "foo.bar",
            "café",
            "_foo",
            "foo_",
            "foo__bar",
            "-foo",
            "foo-",
            "foo--bar",
            "foo_bar-baz",
            "1foo",
            "foo/bar",
        ):
            with self.subTest(name=name):
                before = deepcopy(self.app.state)
                with self.assertRaisesRegex(BrigError, "kebab-case"):
                    self.app.save_profile(name, {"python": "3.12.8"}, {}, {})
                with self.assertRaisesRegex(BrigError, "kebab-case"):
                    self.app.create_project(name, self.root, "python")
                self.assertEqual(self.app.state, before)

    def test_kebab_case_names_are_valid_for_profiles_and_projects(self):
        for name in ("a", "php83", "laravel-project", "api-v2", "project-1", "a" * 64):
            with self.subTest(name=name):
                self.assertEqual(self.app.validate_profile_name(name), name)
                self.assertEqual(self.app.validate_project_name(name), name)
        self.app.save_profile("laravel-dev", {"php": "8.3.15"}, {}, {})
        project = self.app.create_project("laravel-project", self.root, "laravel-dev")
        self.assertEqual(project.name, "laravel-project")
        self.assertEqual(project.profile, "laravel-dev")

    def test_existing_underscore_records_remain_accessible_and_editable(self):
        state = demo_state()
        folder = self.root / "legacy"
        folder.mkdir()
        state.projects[0].name = "legacy_project"
        state.projects[0].path = str(folder)
        app = Application(MemoryStore(state), DemoEngine(), FakeVersionCatalog)
        before = deepcopy(app.project("legacy_project"))
        app.save_profile("web_dev", {"php": "8.2.27"}, {}, {}, editing=True)
        self.assertEqual(app.profile("web_dev").latest.number, 2)
        self.assertEqual(app.resolve_project(None, folder / "subfolder"), before)
        self.assertEqual(app.project("LEGACY_PROJECT").id, before.id)
        app.update_project("legacy_project")
        self.assertEqual(app.project("legacy_project").configuration.number, 2)
        self.assertEqual(app.project("legacy_project").name, "legacy_project")
        app.delete_project("legacy_project")
        app.delete_profile("web_dev")
        self.assertNotIn("web_dev", [profile.name for profile in app.state.profiles])

    def test_legacy_duplicate_names_are_reported_before_format_validation(self):
        state = demo_state()
        state.projects[0].name = "legacy_project"
        app = Application(MemoryStore(state), DemoEngine(), FakeVersionCatalog)
        with self.assertRaisesRegex(BrigError, "already exists"):
            app.validate_profile_name(" web_dev ")
        with self.assertRaisesRegex(BrigError, "already exists"):
            app.validate_project_name(" legacy_project ")
