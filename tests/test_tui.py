"""Flow tests using scripted user choices rather than a real terminal."""

import curses
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from brig.application import Application, demo_state
from brig.catalog import COMPONENTS
from brig.engine import DemoEngine
from brig.errors import BrigError, Cancelled
from brig.tui import InteractiveApp, Terminal
from tests.fakes import MemoryStore, FakeVersionCatalog


class ScriptedTerminal:
    def __init__(self, *, inputs=(), multiples=(), choices=(), confirmed=True):
        self.inputs = iter(inputs)
        self.multiples = iter(multiples)
        self.choices = iter(choices)
        self.confirmed = confirmed
        self.messages = []
        self.selections = []

    def input(self, *args, **kwargs):
        value = next(self.inputs)
        if isinstance(value, Exception):
            raise value
        return value

    def multiple(self, title, options, defaults, *, required_message=None):
        self.selections.append((title, options, defaults))
        return [
            next(
                (
                    option
                    for option in options
                    if option == name or option.endswith(f" · {COMPONENTS[name].label}")
                ),
                name,
            )
            for name in next(self.multiples)
        ]

    def loading(self, message):
        self.messages.append(("Loading", [message]))

    def choose(self, *args, **kwargs):
        return next(self.choices)

    def confirm(self, *args):
        return self.confirmed

    def notice(self, title, lines):
        self.messages.append((title, lines))


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(
            MemoryStore(demo_state()), DemoEngine(), FakeVersionCatalog
        )

    def test_profile_wizard_saves_selected_versions(self):
        terminal = ScriptedTerminal(
            inputs=["custom"],
            multiples=[["python", "php"], ["uv", "composer"], ["redis"]],
            choices=[0, 1, 0, 0, 0, 0],
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        profile = self.app.profile("custom")
        self.assertEqual(profile.latest.runtimes, {"python": "3.12.8", "php": "8.2.27"})
        self.assertEqual(profile.latest.tools, {"uv": "0.5.24", "composer": "2.8.5"})
        self.assertEqual(profile.latest.services, {"redis": "7.4.2"})

    def test_empty_runtime_selection_keeps_wizard_open_and_preserves_name(self):
        selector = TerminalTests().terminal(
            ["\n", curses.KEY_DOWN, " ", "\n", "\n", "\n"]
        )
        terminal = ScriptedTerminal(inputs=["custom"], choices=[0, 0])
        terminal.multiple = selector.multiple
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(
            self.app.profile("custom").latest.runtimes, {"python": "3.12.8"}
        )
        self.assertEqual(self.app.profile("custom").latest.tools, {})
        self.assertEqual(self.app.profile("custom").latest.services, {})
        self.assertTrue(
            any("Select a runtime" in value for value in selector.screen.written)
        )

    def test_empty_profile_name_stays_in_input_until_corrected(self):
        name_input = TerminalTests().terminal(
            ["\n", " ", "\n", "\x15", *"custom", "\n"]
        )
        terminal = ScriptedTerminal(multiples=[["python"], [], []], choices=[0, 0])
        terminal.input = name_input.input
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(
            self.app.profile("custom").latest.runtimes, {"python": "3.12.8"}
        )
        self.assertTrue(
            any(
                "Profile name is required" in value
                for value in name_input.screen.written
            )
        )

    def test_invalid_profile_name_can_cancel_without_reaching_selection(self):
        before = deepcopy(self.app.state)
        name_input = TerminalTests().terminal(["\n", "\x1b"])
        terminal = ScriptedTerminal()
        terminal.input = name_input.input
        with self.assertRaises(Cancelled):
            InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(terminal.selections, [])
        self.assertEqual(self.app.state, before)

    def test_declined_profile_review_does_not_save(self):
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal(
            inputs=["custom"],
            multiples=[["python"], [], []],
            choices=[0, 0],
            confirmed=False,
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(self.app.state, before)

    def test_categories_and_runtime_dependencies_are_visible(self):
        terminal = ScriptedTerminal(
            inputs=["node-dev"],
            multiples=[
                ["node"],
                ["pnpm"],
                ["mysql", "mariadb", "mongodb", "redis", "postgresql"],
            ],
            choices=[0] * 8,
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        tool_options = terminal.selections[1][1]
        self.assertTrue(
            all("Node.js package managers" in option for option in tool_options)
        )
        self.assertEqual(len(tool_options), 3)
        service_options = terminal.selections[2][1]
        self.assertTrue(
            any("Relational databases" in option for option in service_options)
        )
        self.assertTrue(
            any("Document databases" in option for option in service_options)
        )
        self.assertTrue(
            any("Caches / key-value stores" in option for option in service_options)
        )
        self.assertEqual(len(self.app.profile("node-dev").latest.services), 5)

    def test_source_failure_cancel_preserves_state(self):
        before = deepcopy(self.app.state)
        self.app.catalog_factory = lambda: FakeVersionCatalog(
            {"python": BrigError("offline")}
        )
        terminal = ScriptedTerminal(
            inputs=["custom"], multiples=[["python"]], choices=[1]
        )
        with self.assertRaises(Cancelled):
            InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(self.app.state, before)

    def test_fetch_only_selected_components_and_reuse_snapshot_on_save(self):
        from brig.versions import LiveVersionCatalog
        from unittest.mock import Mock

        fetch = Mock(return_value="Tags: 8.3.1\nArchitectures: amd64")
        self.app.catalog_factory = lambda: LiveVersionCatalog(fetch)
        terminal = ScriptedTerminal(
            inputs=["php-only"], multiples=[["php"], [], []], choices=[0, 0]
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(fetch.call_args.args[0].endswith("/php"))

    def test_retry_continues_same_wizard_without_saving_partial_profile(self):
        from brig.versions import LiveVersionCatalog
        from unittest.mock import Mock
        from urllib.error import URLError

        fetch = Mock(
            side_effect=[URLError("offline"), "Tags: 8.3.1\nArchitectures: amd64"]
        )
        self.app.catalog_factory = lambda: LiveVersionCatalog(fetch)
        terminal = ScriptedTerminal(
            inputs=["retry"], multiples=[["php"], [], []], choices=[0, 0, 0]
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(self.app.profile("retry").latest.runtimes, {"php": "8.3.1"})
        self.assertEqual(fetch.call_count, 2)

    def test_edit_replaces_unlisted_versions_without_changing_project_snapshots(self):
        original = deepcopy(self.app.profile("python-dev").latest)
        projects = deepcopy(self.app.state.projects)
        self.app.catalog_factory = lambda: FakeVersionCatalog(
            {"python": ("3.14.0",), "uv": ("0.10.0",), "redis": ("8.0.1",)}
        )
        terminal = ScriptedTerminal(
            multiples=[["python"], ["uv"], ["redis"]], choices=[0, 0, 0, 0]
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard("python-dev")
        self.assertEqual(self.app.profile("python-dev").latest.number, 3)
        self.assertEqual(self.app.profile("python-dev").revisions[1], original)
        self.assertEqual(self.app.state.projects, projects)
        self.assertEqual(
            len(
                [
                    message
                    for message in terminal.messages
                    if message[0] == "Choose an available version"
                ]
            ),
            3,
        )

    def test_cancelled_wizard_does_not_save(self):
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal(inputs=[Cancelled()])
        with self.assertRaises(Cancelled):
            InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(self.app.state, before)

    def test_project_wizard_registers_existing_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            terminal = ScriptedTerminal(inputs=["local", folder], choices=[0])
            InteractiveApp(self.app, terminal, Path("/tmp")).project_wizard()
            project = self.app.project("local")
            self.assertEqual(project.path, str(Path(folder).resolve()))
            self.assertEqual(project.profile, "web-dev")

    def test_declined_project_review_does_not_save(self):
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal(
            inputs=["local", "/tmp"], choices=[0], confirmed=False
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).project_wizard()
        self.assertEqual(self.app.state, before)

    def test_project_wizard_requires_a_profile(self):
        self.app.state.profiles.clear()
        with self.assertRaisesRegex(BrigError, "Create a profile"):
            InteractiveApp(self.app, ScriptedTerminal(), Path("/tmp")).project_wizard()


class FakeScreen:
    def __init__(self, keys, size=(24, 90)):
        self.keys = iter(keys)
        self.size = size
        self.written = []

    def getmaxyx(self):
        return self.size

    def get_wch(self):
        return next(self.keys)

    def erase(self):
        pass

    def refresh(self):
        pass

    def addnstr(self, y, x, value, maximum, style):
        self.written.append(value[:maximum])


class TerminalTests(unittest.TestCase):
    def terminal(self, keys, size=(24, 90)):
        terminal = Terminal.__new__(Terminal)
        terminal.screen = FakeScreen(keys, size)
        terminal.accent = 0
        return terminal

    def test_arrow_navigation_selects_option(self):
        terminal = self.terminal([curses.KEY_DOWN, "\n"])
        self.assertEqual(terminal.choose("Menu", ["one", "two"]), 1)

    def test_version_search_filters_options(self):
        terminal = self.terminal(["/", "3", ".", "1", "1", "\n", "\n"])
        self.assertEqual(
            terminal.choose("Python", ["3.12.8", "3.11.11"], searchable=True), 1
        )

    def test_empty_search_results_can_be_cleared(self):
        terminal = self.terminal(["/", "x", "\n", "/", "\x15", "\n", "\n"])
        self.assertEqual(terminal.choose("Python", ["3.12.8"], searchable=True), 0)

    def test_multi_selection_and_text_editing(self):
        terminal = self.terminal([" ", curses.KEY_DOWN, " ", "\n"])
        self.assertEqual(
            terminal.multiple("Runtimes", ["python", "php"], {"php"}), ["python"]
        )
        terminal = self.terminal(["\x15", "n", "o", "\x7f", "e", "w", "\n"])
        self.assertEqual(terminal.input("Name", "old"), "new")

    def test_required_selection_shows_inline_error_and_can_still_cancel(self):
        terminal = self.terminal(["\n", "\n", "\x1b"])
        with self.assertRaises(Cancelled):
            terminal.multiple(
                "Runtimes",
                ["python", "php"],
                set(),
                required_message="Select a runtime with Space.",
            )
        self.assertTrue(
            any(
                "Select a runtime with Space." in value
                for value in terminal.screen.written
            )
        )

    def test_cancel_and_interrupt(self):
        terminal = self.terminal(["\x1b"])
        with self.assertRaises(Cancelled):
            terminal.choose("Menu", ["one"])
        terminal = self.terminal(["\x03"])
        with self.assertRaises(KeyboardInterrupt):
            terminal.input("Name")

    def test_render_on_small_terminal_displays_resize_message(self):
        terminal = self.terminal([], size=(8, 35))
        terminal.render("Menu", ["one"], "Help")
        self.assertTrue(
            any("Resize terminal" in value for value in terminal.screen.written)
        )
