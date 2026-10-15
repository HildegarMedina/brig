"""Pinned inheritance, additive selections, protected deletion and legacy data."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from brig.application import Application
from brig.errors import BrigError
from brig.models import ProfileParent, State
from brig.persistence.codec import decode_state
from brig.persistence.profile_yaml import legacy_profile, profile_path, render_profile
from brig.persistence.store import JsonStateStore
from brig.profile_inheritance import resolve_base, validate_inherited, would_cycle
from brig.ui.presentation import configuration_lines
from brig.ui.tui.app import InteractiveApp, launch
from brig.ui.tui.profile_inheritance import choose_parent
from tests.demo_engine import DemoEngine
from tests.fakes import FakeVersionCatalog, MemoryStore
from tests.test_tui import ScriptedTerminal


class InheritedTerminal(ScriptedTerminal):
    def choose(self, *args, **kwargs):
        if args[0] == "Base profile":
            return 1
        return super().choose(*args, **kwargs)


class ProfileInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(MemoryStore(State()), DemoEngine(), FakeVersionCatalog)
        self.app.save_profile(
            "base",
            {"node": "22.13.1"},
            {"pnpm": "9.15.0"},
            {"redis": "7.4.2"},
            "codex",
            agents=["codex"],
        )

    def child(self, name="child", **options):
        return self.app.save_profile(name, {}, {}, {}, base="base", **options)

    def test_child_inherits_exact_configuration_and_default_agent(self):
        child = self.child()
        base = self.app.profile("base").latest
        self.assertEqual(child.latest.extends, ProfileParent("base", 1))
        self.assertEqual(child.latest.runtimes, base.runtimes)
        self.assertEqual(child.latest.tools, base.tools)
        self.assertEqual(child.latest.services, base.services)
        self.assertEqual(child.latest.selected_agents, ["codex"])
        self.assertEqual(child.latest.agent, "codex")
        self.assertIn("Inherits   base · version 1", configuration_lines(child.latest))

    def test_new_components_are_added_and_base_objects_are_not_modified(self):
        original = deepcopy(self.app.profile("base"))
        child = self.app.save_profile(
            "child",
            {"python": "3.12.8"},
            {"uv": "0.5.24"},
            {"mysql": "8.4.3"},
            "claude",
            agents=["claude"],
            base="BASE",
        )
        self.assertEqual(child.latest.runtimes, {"node": "22.13.1", "python": "3.12.8"})
        self.assertEqual(child.latest.selected_agents, ["codex", "claude"])
        self.assertEqual(self.app.profile("base"), original)
        self.assertEqual(child.latest.extends.profile, "base")

    def test_inherited_releases_are_not_refetched_from_upstream(self):
        catalog = FakeVersionCatalog({"python": ("3.12.8",)})
        self.app.save_profile(
            "child", {"python": "3.12.8"}, {}, {}, base="base", catalog=catalog
        )
        self.assertEqual(catalog.calls, ["python"])

    def test_conflicting_inherited_versions_and_invalid_references_do_not_save(self):
        original = deepcopy(self.app.state)
        for options, message in (
            ({"base_version": 99}, "Unknown base"),
            ({"base_version": True}, "Invalid base"),
            ({"base_version": "1"}, "Invalid base"),
        ):
            with (
                self.subTest(options=options),
                self.assertRaisesRegex(BrigError, message),
            ):
                self.child(**options)
        with self.assertRaisesRegex(BrigError, "overridden"):
            self.app.save_profile("child", {"node": "20.18.2"}, {}, {}, base="base")
        with self.assertRaisesRegex(BrigError, "requires a base"):
            self.app.save_profile("child", {}, {}, {}, base_version=1)
        with self.assertRaisesRegex(BrigError, "does not inherit"):
            self.app.save_profile("base", {}, {}, {}, editing=True, update_base=True)
        with self.assertRaisesRegex(BrigError, "Invalid base"):
            resolve_base(self.app.state.profiles, ProfileParent(None, 1))
        self.assertEqual(self.app.state, original)

    def test_chain_is_supported_and_self_or_indirect_cycles_are_rejected(self):
        self.child()
        grandchild = self.app.save_profile("grandchild", {}, {}, {}, base="child")
        self.assertEqual(grandchild.latest.runtimes, {"node": "22.13.1"})
        for name, parent in (("base", "base"), ("base", "grandchild")):
            with self.assertRaisesRegex(BrigError, "cycles"):
                self.app.save_profile(name, {}, {}, {}, editing=True, base=parent)
        self.assertFalse(would_cycle(self.app.state.profiles, "unrelated", "unknown"))
        # Shared ancestry can be visited through different historical versions.
        self.app.save_profile("child", {}, {}, {}, editing=True)
        self.assertFalse(would_cycle(self.app.state.profiles, "unrelated", "child"))

    def test_deletion_protection_includes_historical_base_references(self):
        self.child()
        with self.assertRaisesRegex(BrigError, "Inherited by profiles: child"):
            self.app.delete_profile("base")
        self.app.delete_profile("child")
        self.app.delete_profile("base")
        self.assertEqual(self.app.state.profiles, [])

    def test_base_update_is_explicit_and_does_not_change_project_snapshots(self):
        self.child()
        with tempfile.TemporaryDirectory() as folder:
            project = self.app.create_project("api", Path(folder), "child")
        pinned = deepcopy(project.configuration)
        self.app.save_profile(
            "base", {"node": "20.18.2"}, {}, {}, "codex", editing=True
        )
        self.app.save_profile("child", {}, {}, {}, editing=True)
        self.assertEqual(self.app.profile("child").latest.extends.version, 1)
        self.app.save_profile("child", {}, {}, {}, editing=True, update_base=True)
        updated = self.app.profile("child").latest
        self.assertEqual(updated.extends.version, 2)
        self.assertEqual(updated.runtimes["node"], "20.18.2")
        self.assertEqual(project.configuration, pinned)
        # Older versions can be selected explicitly for another child.
        self.assertEqual(self.child("older", base_version=1).latest.extends.version, 1)

    def test_yaml_and_state_round_trip_preserve_the_pinned_relationship(self):
        self.child()
        text = render_profile("child", self.app.profile("child").latest)
        self.assertIn('extends:\n  profile: "base"\n  version: 1', text)
        self.assertIn("schema_version: 2", text)
        self.assertIn("\nversion: 1\n", text)
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStateStore(Path(folder))
            store.save(self.app.state)
            self.assertEqual(store.load(), self.app.state)
            document = profile_path(Path(folder), "child", 1)
            self.assertEqual(document.parent.name, "versions")
            self.assertEqual(document.read_text(), text)

    def test_corrupt_relationships_and_removed_inherited_components_are_rejected(self):
        self.child()
        raw = {"schema_version": 2, **asdict(self.app.state)}
        mutations = [
            lambda data: data["profiles"][1]["versions"][0]["extends"].update(
                profile="unknown"
            ),
            lambda data: data["profiles"][1]["versions"][0]["extends"].update(
                version=0
            ),
            lambda data: data["profiles"][1]["versions"][0]["extends"].update(
                version=False
            ),
            lambda data: data["profiles"][0]["versions"][0].update(
                extends={"profile": "child", "version": 1}
            ),
            lambda data: data["profiles"][1]["versions"][0]["tools"].clear(),
        ]
        for mutate in mutations:
            modified = deepcopy(raw)
            mutate(modified)
            with self.subTest(modified=modified), self.assertRaises(BrigError):
                decode_state(modified)
        modified = deepcopy(self.app.profile("child").latest)
        modified.agents = ["claude"]
        with self.assertRaisesRegex(BrigError, "agents cannot be removed"):
            validate_inherited(modified, self.app.profile("base").latest)

    def test_legacy_state_and_yaml_are_read_and_new_documents_use_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            store = JsonStateStore(directory)
            raw = {"schema_version": 1, **asdict(self.app.state)}
            for profile in raw["profiles"]:
                profile["revisions"] = profile.pop("versions")
                for version in profile["revisions"]:
                    version.pop("extends")
            store.path.write_text(json.dumps(raw))
            old_path, contents = legacy_profile(
                directory, "base", self.app.profile("base").latest
            )
            old_path.parent.mkdir(parents=True)
            old_path.write_text(contents)
            loaded = store.load()
            self.assertEqual(loaded, self.app.state)
            store.save(loaded)
            self.assertEqual(old_path.read_text(), contents)
            self.assertTrue(profile_path(directory, "base", 1).exists())
            self.assertEqual(json.loads(store.path.read_text())["schema_version"], 3)
            # A changed legacy document must not be silently bypassed on migration.
            profile_path(directory, "base", 1).unlink()
            old_path.write_text("edited")
            with self.assertRaisesRegex(
                BrigError, "Legacy profile document was modified"
            ):
                store.save(loaded)

    def test_wizard_shows_only_additions_and_preserves_inherited_selections(self):
        terminal = InheritedTerminal(
            inputs=["child"],
            multiples=[["python"], ["uv"], ["mysql"], ["claude"]],
            choices=[0, 0, 0, 0, 0],
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        version = self.app.profile("child").latest
        self.assertEqual(version.extends, ProfileParent("base", 1))
        self.assertEqual(version.selected_agents, ["codex", "claude"])
        for _, options, _ in terminal.selections:
            self.assertFalse(
                any(
                    item.startswith("Runtimes · Node.js")
                    or "pnpm" in item
                    or "Redis" in item
                    or "codex" in item
                    for item in options
                )
            )

    def test_wizard_allows_no_additions_and_updating_or_keeping_base_version(self):
        terminal = ScriptedTerminal(
            inputs=["child"], multiples=[[], [], [], []], choices=[0]
        )
        view = InteractiveApp(self.app, terminal, Path("/tmp"))
        view.profile_wizard(base="base", base_version=1)
        self.assertEqual(self.app.profile("child").latest.runtimes, {"node": "22.13.1"})
        self.app.save_profile(
            "base", {"node": "20.18.2"}, {}, {}, "codex", editing=True
        )
        for update, number in ((0, 1), (1, 2)):
            terminal = ScriptedTerminal(multiples=[[], [], [], []], choices=[update])
            InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard("child")
            self.assertEqual(self.app.profile("child").latest.extends.version, number)

    def test_updating_base_keeps_only_the_childs_own_defaults(self):
        self.app.save_profile(
            "child",
            {"python": "3.12.8"},
            {"uv": "0.5.24"},
            {"mysql": "8.4.3"},
            base="base",
        )
        self.app.save_profile("base", {"php": "8.3.15"}, {}, {}, "claude", editing=True)
        terminal = ScriptedTerminal(
            multiples=[["python"], ["uv"], ["mysql"], []],
            choices=[0, 0, 0],
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard(
            "child", update_base=True
        )
        runtime_defaults = terminal.selections[0][2]
        tool_defaults = terminal.selections[1][2]
        agent_defaults = terminal.selections[3][2]
        self.assertTrue(any("Python" in option for option in runtime_defaults))
        self.assertFalse(any("Node.js" in option for option in runtime_defaults))
        self.assertTrue(any("uv" in option for option in tool_defaults))
        self.assertFalse(any("pnpm" in option for option in tool_defaults))
        self.assertFalse(any("codex" in option for option in agent_defaults))
        updated = self.app.profile("child").latest
        self.assertEqual(updated.runtimes, {"php": "8.3.15", "python": "3.12.8"})
        self.assertEqual(updated.tools, {"uv": "0.5.24"})
        self.assertEqual(updated.selected_agents, ["claude"])

    def test_all_inherited_components_skip_empty_selection_steps(self):
        base = self.app.profile("base").latest
        base.runtimes = {
            "node": "22.13.1",
            "python": "3.12.8",
            "php": "8.3.15",
            "go": "1.27.2",
            "rust": "1.99.0",
            "java": "21",
        }
        base.agents = ["claude", "codex", "opencode"]
        terminal = ScriptedTerminal(inputs=["child"], multiples=[[], []], choices=[0])
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard(
            base="base", base_version=1
        )
        self.assertEqual(len(terminal.selections), 2)
        self.assertEqual(
            self.app.profile("child").latest.selected_agents, base.selected_agents
        )

    def test_parent_selector_handles_empty_catalog_invalid_options_and_explicit_updates(
        self,
    ):
        empty = Application(MemoryStore(State()), DemoEngine(), FakeVersionCatalog)
        self.assertIsNone(choose_parent(empty, Mock(), None))
        with self.assertRaisesRegex(BrigError, "requires --base"):
            choose_parent(self.app, Mock(), None, base_version=1)
        with self.assertRaisesRegex(BrigError, "does not inherit"):
            choose_parent(
                self.app, Mock(), self.app.profile("base").latest, update_base=True
            )
        self.child()
        self.app.save_profile(
            "base", {"node": "20.18.2"}, {}, {}, "codex", editing=True
        )
        parent = choose_parent(
            self.app, Mock(), self.app.profile("child").latest, update_base=True
        )
        self.assertEqual(parent.version, 2)

    def test_launch_passes_inheritance_options_to_the_shared_wizard(self):
        screen = Mock()
        with (
            patch(
                "brig.ui.tui.app.curses.wrapper", side_effect=lambda run: run(screen)
            ),
            patch("brig.ui.tui.app.Terminal"),
            patch("brig.ui.tui.app.InteractiveApp") as interactive,
        ):
            self.assertTrue(
                launch(
                    self.app,
                    Path("/tmp"),
                    "profile-create",
                    base="base",
                    base_version=1,
                )
            )
            interactive.return_value.profile_wizard.assert_called_with(
                base="base", base_version=1
            )
            self.assertTrue(
                launch(
                    self.app, Path("/tmp"), "profile-edit", "child", update_base=True
                )
            )
            interactive.return_value.profile_wizard.assert_called_with(
                "child", update_base=True
            )
