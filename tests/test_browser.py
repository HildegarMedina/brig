"""Keyboard navigation and summary-to-detail transitions in list browsers."""

import curses
import unittest
from pathlib import Path
from unittest.mock import patch

from brig.application import Application
from brig.errors import Cancelled
from brig.ui.listings import list_records
from brig.ui.tui.browser import browse_list, choose_card
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
                records = list_records(app, kind)
                with (
                    patch(
                        f"brig.ui.tui.{kind}s.choose_card",
                        side_effect=[len(records), Cancelled],
                    ) as chooser,
                    patch.object(view, f"{kind}_wizard") as create,
                ):
                    getattr(view, f"{kind}s")()
                create.assert_called_once_with()
                self.assertEqual(chooser.call_args_list[0].args[2][:-1], records)
                self.assertEqual(
                    chooser.call_args_list[0].args[2][-1], (f"+ Create {kind}", [])
                )

    def test_main_project_cards_keep_environment_management(self):
        app = Application(MemoryStore(demo_state()), DemoEngine(), FakeVersionCatalog)
        ui = test_tui.TerminalTests().terminal([])
        view = ProjectViews(app, ui, Path("/tmp"))
        with (
            patch("brig.ui.tui.projects.choose_card", side_effect=[1, Cancelled]),
            patch.object(view, "project_detail") as detail,
        ):
            view.projects()
        detail.assert_called_once_with(app.state.projects[1].name)

    def test_selection_changes_only_card_border_without_background_highlight(self):
        ui = test_tui.TerminalTests().terminal(["\n"], size=(24, 100))
        ui.accent = 1 << 8
        ui.card_styles = (3 << 8,)
        ui.card_selection_style = curses.A_BOLD | (9 << 8)
        choose_card(
            ui, "Profiles", [("first", ["Version 1"]), ("second", ["Version 2"])], 0
        )
        for text, style in ui.screen.drawn:
            self.assertFalse(style & curses.A_REVERSE)
            if "first" in text or "second" in text or "Version" in text:
                self.assertEqual(style, 0)
        borders = [(text, style) for text, style in ui.screen.drawn if "┌" in text]
        self.assertEqual(borders[0][1], ui.card_selection_style)
        self.assertEqual(borders[1][1], ui.card_styles[0])
        self.assertIn(("│", ui.card_selection_style), ui.screen.drawn)

    def test_border_selection_moves_with_arrow_keys(self):
        ui = test_tui.TerminalTests().terminal([curses.KEY_DOWN, "\n"])
        ui.card_styles = (3 << 8,)
        ui.card_selection_style = curses.A_BOLD | (9 << 8)
        choose_card(
            ui, "Profiles", [("first", ["Version 1"]), ("second", ["Version 2"])], 0
        )
        borders = [style for text, style in ui.screen.drawn if "┌" in text]
        self.assertEqual(
            borders,
            [
                ui.card_selection_style,
                ui.card_styles[0],
                ui.card_styles[0],
                ui.card_selection_style,
            ],
        )

    def test_cards_navigate_and_show_keyboard_controls(self):
        ui = test_tui.TerminalTests().terminal([curses.KEY_DOWN, "\n"])
        result = choose_card(
            ui, "Profiles", [("first", ["Version 1"]), ("second", ["Version 2"])], 0
        )
        self.assertEqual(result, 1)
        self.assertTrue(
            any(
                "enter details" in row and "esc exit" in row
                for row in ui.screen.written
            )
        )

    def test_pagination_keeps_last_card_reachable(self):
        ui = test_tui.TerminalTests().terminal([curses.KEY_UP, "\n"], size=(16, 45))
        result = choose_card(
            ui, "Profiles", [(f"profile-{i}", [f"Version {i}"]) for i in range(12)], 0
        )
        self.assertEqual(result, 11)
        self.assertTrue(any("profile-11" in row for row in ui.screen.written))

    def test_small_terminal_can_select_using_compact_menu(self):
        ui = test_tui.TerminalTests().terminal([curses.KEY_DOWN, "\n"], size=(12, 45))
        self.assertEqual(
            choose_card(
                ui, "Profiles", [("first", ["Version 1"]), ("second", ["Version 2"])], 0
            ),
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
