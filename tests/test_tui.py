"""Flow tests using scripted user choices rather than a real terminal."""

import curses
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from brig.application import Application, demo_state
from brig.engine import DemoEngine
from brig.errors import BrigError, Cancelled
from brig.tui import InteractiveApp, Terminal
from tests.fakes import MemoryStore


class ScriptedTerminal:
    def __init__(self, *, inputs=(), multiples=(), choices=(), confirmed=True):
        self.inputs = iter(inputs)
        self.multiples = iter(multiples)
        self.choices = iter(choices)
        self.confirmed = confirmed
        self.messages = []

    def input(self, *args, **kwargs):
        value = next(self.inputs)
        if isinstance(value, Exception):
            raise value
        return value

    def multiple(self, *args, **kwargs):
        return next(self.multiples)

    def choose(self, *args, **kwargs):
        return next(self.choices)

    def confirm(self, *args):
        return self.confirmed

    def notice(self, title, lines):
        self.messages.append((title, lines))


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(MemoryStore(demo_state()), DemoEngine())

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
