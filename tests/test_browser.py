"""Keyboard navigation and summary-to-detail transitions in list browsers."""

import curses
import unittest
from pathlib import Path
from unittest.mock import patch

from brig.application import Application
from brig.errors import Cancelled
from brig.ui.listings import list_rows
from brig.ui.tui.browser import browse_list, choose_list
from brig.ui.tui.profiles import ProfileViews
from brig.ui.tui.projects import ProjectViews
from tests import test_tui
from tests.demo_engine import DemoEngine
from tests.fakes import FakeVersionCatalog, MemoryStore, demo_state


class BrowserTests(unittest.TestCase):
    def test_main_menu_reuses_list_summaries_and_keeps_creation_actions(self):
        app = Application(MemoryStore(demo_state()), DemoEngine(), FakeVersionCatalog)
        for kind, view_class in (("profile", ProfileViews), ("project", ProjectViews)):
            with self.subTest(kind=kind):
                ui = test_tui.TerminalTests().terminal([])
                view = view_class(app, ui, Path("/tmp"))
                records = list_rows(app, kind)
                with (
                    patch(
                        f"brig.ui.tui.{kind}s.choose_list",
                        side_effect=[len(records), Cancelled],
                    ) as chooser,
                    patch.object(view, f"{kind}_wizard") as create,
                ):
                    getattr(view, f"{kind}s")()
                create.assert_called_once_with()
                self.assertEqual(chooser.call_args_list[0].args[2][:-1], records)
                self.assertEqual(
                    chooser.call_args_list[0].args[2][-1], f"+ Create {kind}"
                )

    def test_main_project_lists_keep_environment_management(self):
        app = Application(MemoryStore(demo_state()), DemoEngine(), FakeVersionCatalog)
        ui = test_tui.TerminalTests().terminal([])
        view = ProjectViews(app, ui, Path("/tmp"))
        with (
            patch("brig.ui.tui.projects.choose_list", side_effect=[1, Cancelled]),
            patch.object(view, "project_detail") as detail,
        ):
            view.projects()
        detail.assert_called_once_with(app.state.projects[1].name)

    def test_selection_uses_a_marker_without_background_highlight(self):
        ui = test_tui.TerminalTests().terminal(["\n"], size=(24, 100))
        choose_list(ui, "Profiles", ["first · version 1", "second · version 2"], 0)
        selected = [
            (text, style) for text, style in ui.screen.drawn if "› first" in text
        ]
        self.assertEqual(len(selected), 1)
        self.assertFalse(selected[0][1] & curses.A_REVERSE)
        self.assertTrue(selected[0][0].endswith("version 1"))

    def test_lists_navigate_and_show_keyboard_controls(self):
        ui = test_tui.TerminalTests().terminal([curses.KEY_DOWN, "\n"])
        result = choose_list(
            ui, "Profiles", ["first · version 1", "second · version 2"], 0
        )
        self.assertEqual(result, 1)
        self.assertTrue(
            any(
                "enter details" in row and "esc exit" in row
                for row in ui.screen.written
            )
        )

    def test_pagination_keeps_last_row_reachable(self):
        ui = test_tui.TerminalTests().terminal([curses.KEY_UP, "\n"], size=(16, 45))
        result = choose_list(
            ui, "Profiles", [f"profile-{i} · version {i}" for i in range(12)], 0
        )
        self.assertEqual(result, 11)
        self.assertTrue(any("profile-11" in row for row in ui.screen.written))

    def test_small_terminal_can_select_using_compact_menu(self):
        ui = test_tui.TerminalTests().terminal([curses.KEY_DOWN, "\n"], size=(12, 45))
        self.assertEqual(
            choose_list(ui, "Profiles", ["first · version 1", "second · version 2"], 0),
            1,
        )

    def test_enter_opens_details_and_escape_returns_to_same_selection_then_exits(self):
        app = Application(MemoryStore(demo_state()), DemoEngine(), FakeVersionCatalog)
        for kind in ("profile", "project"):
            with self.subTest(kind=kind):
                ui = test_tui.TerminalTests().terminal(
                    [curses.KEY_DOWN, "\n", "\x1b", "\x1b"]
                )
                with (
                    patch.object(ui, "notice", wraps=ui.notice) as details,
                    self.assertRaises(Cancelled),
                ):
                    browse_list(app, ui, kind)
                entries = (
                    app.state.profiles if kind == "profile" else app.state.projects
                )
                self.assertEqual(details.call_args.args[0], entries[1].name)
                self.assertTrue(
                    any("Version" in line for line in details.call_args.args[1])
                )
                if kind == "project":
                    self.assertTrue(
                        any("Folder" in line for line in details.call_args.args[1])
                    )
