"""Dashboard layout, keyboard navigation and existing action integration."""

import curses
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from brig.application import Application
from brig.ui.tui.dashboard import Dashboard
from tests import test_tui
from tests.demo_engine import DemoEngine
from tests.fakes import FakeVersionCatalog, MemoryStore, demo_state


class DashboardTests(unittest.TestCase):
    def dashboard(self, keys, *, size=(32, 110), empty=False):
        app = Application(
            MemoryStore(None if empty else demo_state()),
            DemoEngine(),
            FakeVersionCatalog,
        )
        ui = test_tui.TerminalTests().terminal(keys, size=size)
        with patch(
            "brig.ui.tui.dashboard_render.curses.has_colors", return_value=False
        ):
            dashboard = Dashboard(app, ui, Path("/tmp/brig-test"), Mock())
        return dashboard

    def test_wide_layout_has_navigation_status_and_selected_details(self):
        dashboard = self.dashboard(["\x1b"])
        dashboard.run()
        output = dashboard.ui.screen.written
        for label in (
            "Projects",
            "Profiles",
            "Settings",
            "OVERVIEW",
            "website",
            "stopped",
            "web_dev",
            "Enter  actions",
        ):
            self.assertTrue(any(label in row for row in output), label)
        self.assertFalse(
            any(style & curses.A_REVERSE for _, style in dashboard.ui.screen.drawn)
        )

    def test_arrows_change_preview_without_requerying_docker(self):
        dashboard = self.dashboard([curses.KEY_DOWN, curses.KEY_UP, "\x1b"])
        with patch.object(
            dashboard.app, "project_status", wraps=dashboard.app.project_status
        ) as status:
            dashboard.run()
        self.assertEqual(status.call_count, len(dashboard.app.state.projects))
        self.assertTrue(any("api" in row for row in dashboard.ui.screen.written))

    def test_tabs_switch_and_creation_reuses_existing_wizard(self):
        dashboard = self.dashboard([curses.KEY_RIGHT, "c", "\x1b"])
        dashboard.run()
        dashboard.views.profile_wizard.assert_called_once_with()
        dashboard.views.project_wizard.assert_not_called()

    def test_enter_opens_existing_project_actions_for_selected_project(self):
        dashboard = self.dashboard([curses.KEY_DOWN, "\n", "\x1b"])
        dashboard.run()
        dashboard.views.project_detail.assert_called_once_with("api")

    def test_start_stop_shortcut_runs_outside_curses_and_refreshes_status(self):
        dashboard = self.dashboard(["s", "s", "\x1b"])
        with patch.object(
            dashboard.ui, "external", side_effect=lambda action: action()
        ) as external:
            dashboard.run()
        self.assertEqual(external.call_count, 2)
        self.assertFalse(dashboard.app.project("website").running)
        self.assertTrue(any("running" in row for row in dashboard.ui.screen.written))

    def test_read_only_list_opens_details_and_ignores_mutating_shortcuts(self):
        dashboard = self.dashboard(
            ["s", "c", curses.KEY_RIGHT, curses.KEY_DOWN, "\n", "\x1b"]
        )
        before = deepcopy(dashboard.app.state)
        with patch.object(dashboard.ui, "notice") as notice:
            dashboard.run(read_only=True)
        self.assertEqual(dashboard.app.state, before)
        dashboard.views.project_wizard.assert_not_called()
        self.assertEqual(notice.call_args.args[0], "api")

    def test_small_and_ascii_terminals_remain_navigable(self):
        dashboard = self.dashboard([curses.KEY_DOWN, "\x1b"], size=(12, 45))
        with patch("brig.ui.tui.terminal.locale.getencoding", return_value="ascii"):
            dashboard.run(read_only=True)
        for row in dashboard.ui.screen.written:
            row.encode("ascii")
        self.assertTrue(any("> api" in row for row in dashboard.ui.screen.written))

    def test_empty_workspace_still_allows_creation(self):
        dashboard = self.dashboard(["c", "\x1b"], empty=True)
        dashboard.run()
        dashboard.views.project_wizard.assert_called_once_with()
        self.assertTrue(
            any(
                "Your workspace starts here" in row
                for row in dashboard.ui.screen.written
            )
        )

    def test_wide_layout_keeps_draws_inside_screen_and_clips_wide_paths(self):
        dashboard = self.dashboard(["\x1b"])
        dashboard.app.state.projects[0].path = "/workspace/" + "项目" * 60
        dashboard.run()
        height, width = dashboard.ui.screen.size
        for y, x, text in dashboard.ui.screen.positions:
            self.assertLess(y, height)
            self.assertLess(x + len(text), width)
        self.assertTrue(any("..." in row for row in dashboard.ui.screen.written))
