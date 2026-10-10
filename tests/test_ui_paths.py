"""Exercise terminal lifecycle, dashboard controls and management actions."""

import curses
import io
import runpy
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from brig.application import Application
from brig.errors import BrigError, Cancelled
from brig.ui import cli
from brig.ui.tui.app import InteractiveApp, launch
from brig.ui.tui.browser import browse_list
from brig.ui.tui.dashboard_render import DashboardRenderer
from brig.ui.tui.profiles import ProfileViews
from brig.ui.tui.projects import ProjectViews
from brig.ui.tui.terminal import Terminal
from tests import test_dashboard, test_tui
from tests.demo_engine import DemoEngine
from tests.fakes import FakeVersionCatalog, MemoryStore, demo_state


class UiPathTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(
            MemoryStore(demo_state()), DemoEngine(), FakeVersionCatalog
        )

    def test_cli_reports_terminal_errors_and_interruptions(self):
        for exception, expected in (
            (curses.error("bad terminal"), 1),
            (KeyboardInterrupt(), 130),
        ):
            with (
                patch("brig.ui.cli.Application", side_effect=exception),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(cli.main(["project", "list"]), expected)
        args = cli.parser().parse_args(["project", "update", "website"])
        self.assertIn("latest", cli.dispatch(self.app, args))

    def test_module_entrypoints_exit_with_cli_result(self):
        with (
            patch("brig.ui.cli.main", return_value=7),
            self.assertRaises(SystemExit) as error,
        ):
            runpy.run_module("brig", run_name="__main__")
        self.assertEqual(error.exception.code, 7)
        with (
            patch("sys.argv", ["brig", "--version"]),
            redirect_stdout(io.StringIO()),
            warnings.catch_warnings(),
            self.assertRaises(SystemExit) as error,
        ):
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("brig.ui.cli", run_name="__main__")
        self.assertEqual(error.exception.code, 0)

    def test_launch_routes_all_actions_and_handles_cancel_and_failure(self):
        routes = {
            "profile-create": "profile_wizard",
            "profile-edit": "profile_wizard",
            "profile-delete": "delete_profile",
            "project-create": "project_wizard",
            "project-delete": "delete_project",
            "home": "home",
        }
        for action, method in routes.items():
            interactive = Mock()
            with (
                patch("brig.ui.tui.app.InteractiveApp", return_value=interactive),
                patch("brig.ui.tui.app.Terminal"),
                patch(
                    "brig.ui.tui.app.curses.wrapper",
                    side_effect=lambda run: run(Mock()),
                ),
            ):
                self.assertTrue(launch(self.app, Path("/tmp"), action, "website"))
            getattr(interactive, method).assert_called_once()
        for action, section in (
            ("profile-list", "Profiles"),
            ("project-list", "Projects"),
        ):
            with (
                patch("brig.ui.tui.app.Terminal"),
                patch("brig.ui.tui.app.Dashboard") as dashboard,
                patch(
                    "brig.ui.tui.app.curses.wrapper",
                    side_effect=lambda run: run(Mock()),
                ),
            ):
                self.assertTrue(launch(self.app, Path("/tmp"), action))
                dashboard.return_value.run.assert_called_once_with(
                    section, read_only=True
                )
        for exception, expected in ((Cancelled(), True), (BrigError("failed"), False)):
            interactive = Mock()
            interactive.home.side_effect = exception
            with (
                patch("brig.ui.tui.app.InteractiveApp", return_value=interactive),
                patch("brig.ui.tui.app.Terminal"),
                patch(
                    "brig.ui.tui.app.curses.wrapper",
                    side_effect=lambda run: run(Mock()),
                ),
            ):
                self.assertEqual(launch(self.app, Path("/tmp")), expected)
            if not expected:
                interactive.ui.notice.assert_called_once()

    def test_interactive_facade_delegates_to_existing_views(self):
        interactive = InteractiveApp(self.app, Mock(), Path("/tmp"))
        interactive.profile_views, interactive.project_views = Mock(), Mock()
        interactive.profiles()
        interactive.projects()
        interactive.delete_project("website")
        interactive.profile_views.profiles.assert_called_once()
        interactive.project_views.projects.assert_called_once()
        interactive.project_views.delete_project.assert_called_once_with("website")
        with patch("brig.ui.tui.app.Dashboard") as dashboard:
            interactive.home()
            dashboard.return_value.run.assert_called_once_with()

    def test_empty_browser_reports_how_to_create_records(self):
        app = Application(MemoryStore(), DemoEngine(), FakeVersionCatalog)
        ui = Mock()
        browse_list(app, ui, "profile")
        self.assertIn("brig profile create", ui.notice.call_args.args[1][0])

    def test_profile_actions_and_management_errors(self):
        for action in (0, 1, 2):
            ui = Mock()
            ui.choose.return_value = action
            view = ProfileViews(self.app, ui, Path("/tmp"))
            with (
                patch("brig.ui.tui.profiles.choose_list", side_effect=[0, Cancelled]),
                patch.object(view, "profile_wizard") as edit,
                patch.object(view, "delete_profile") as delete,
            ):
                view.profiles()
            if action == 0:
                ui.notice.assert_called_once()
            elif action == 1:
                edit.assert_called_once_with("web_dev")
            else:
                delete.assert_called_once_with("web_dev")
        ui = Mock()
        with patch(
            "brig.ui.tui.profiles.choose_list",
            side_effect=[BrigError("unavailable"), Cancelled],
        ):
            ProfileViews(self.app, ui, Path("/tmp")).profiles()
        self.assertEqual(ui.notice.call_args.args[0], "Could not complete action")
        self.assertEqual(
            ProfileViews(self.app, ui, Path("/tmp"))._select_versions(
                "Empty", {}, {}, FakeVersionCatalog()
            ),
            {},
        )

    def test_project_actions_use_existing_application_flows(self):
        for action in (0, 1, 2, 3, 4, 5, 7):
            ui = Mock()
            ui.choose.side_effect = [action, *([0] if action == 3 else []), Cancelled]
            ui.confirm.return_value = True
            ui.external.side_effect = lambda run: run()
            ProjectViews(self.app, ui, Path("/tmp")).project_detail("website")
            self.assertTrue(ui.notice.called)
        ui = Mock()
        ui.choose.side_effect = [5, Cancelled]
        ui.confirm.return_value = False
        ProjectViews(self.app, ui, Path("/tmp")).project_detail("website")
        ui.notice.assert_not_called()
        ui.choose.side_effect = [6, Cancelled]
        view = ProjectViews(self.app, ui, Path("/tmp"))
        with patch.object(view, "delete_project", return_value=False) as delete:
            view.project_detail("website")
        delete.assert_called_once_with("website")

    def test_project_view_errors_are_presented(self):
        ui = Mock()
        ui.external.side_effect = lambda action: action()
        with patch(
            "brig.ui.tui.projects.choose_list",
            side_effect=[BrigError("unavailable"), Cancelled],
        ):
            ProjectViews(self.app, ui, Path("/tmp")).projects()
        self.assertEqual(ui.notice.call_args.args[0], "Could not complete action")
        ui.choose.side_effect = [1, Cancelled]
        with patch.object(self.app, "start", side_effect=BrigError("unavailable")):
            ProjectViews(self.app, ui, Path("/tmp")).project_detail("website")
        self.assertTrue(ui.notice.call_args.kwargs["error"])

    def test_terminal_color_and_cursor_fallbacks_do_not_crash(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("brig.ui.tui.terminal.curses.curs_set", side_effect=curses.error),
            patch("brig.ui.tui.terminal.curses.has_colors", return_value=True),
            patch("brig.ui.tui.terminal.curses.start_color"),
            patch(
                "brig.ui.tui.terminal.curses.use_default_colors",
                side_effect=curses.error,
            ),
            patch("brig.ui.tui.terminal.curses.init_pair") as colors,
            patch("brig.ui.tui.terminal.curses.color_pair", return_value=0),
        ):
            Terminal(Mock())
        colors.assert_any_call(1, curses.COLOR_CYAN, curses.COLOR_BLACK)

    def test_terminal_external_action_restores_terminal_even_on_failure(self):
        ui = test_tui.TerminalTests().terminal([])
        with (
            patch("brig.ui.tui.terminal.curses.def_prog_mode"),
            patch("brig.ui.tui.terminal.curses.endwin"),
            patch("brig.ui.tui.terminal.curses.reset_prog_mode") as reset,
            self.assertRaisesRegex(ValueError, "failed"),
        ):
            ui.external(Mock(side_effect=ValueError("failed")))
        reset.assert_called_once()

    def test_terminal_handles_write_errors_empty_choices_and_scroll_up(self):
        ui = test_tui.TerminalTests().terminal([])
        ui.loading("Fetching Python versions")
        self.assertTrue(any("Fetching Python" in row for row in ui.screen.written))
        with patch.object(ui.screen, "addnstr", side_effect=curses.error):
            ui._write(1, 1, "safe")
        with self.assertRaisesRegex(BrigError, "No options"):
            ui.choose("Empty", [])
        ui = test_tui.TerminalTests().terminal(
            [curses.KEY_DOWN, curses.KEY_UP, "\n"], size=(12, 45)
        )
        ui.notice("Details", [str(i) for i in range(10)])
        ui = test_tui.TerminalTests().terminal(["\n", "\x1b"])
        with self.assertRaises(Cancelled):
            ui.input("Required", required_message="Enter a value")
        self.assertTrue(any("Enter a value" in row for row in ui.screen.written))
        ui = test_tui.TerminalTests().terminal([curses.KEY_UP, " ", "\n"])
        self.assertEqual(ui.multiple("Options", ["first", "second"], set()), ["second"])

    def test_dashboard_profile_edit_delete_back_and_cancel(self):
        case = test_dashboard.DashboardTests()
        for action in (0, 1, 2, Cancelled()):
            dashboard = case.dashboard([])
            with (
                patch.object(dashboard.ui, "choose", side_effect=[action])
                if isinstance(action, Cancelled)
                else patch.object(dashboard.ui, "choose", return_value=action)
            ):
                dashboard.open("Profiles", dashboard.items("Profiles")[0], False)
            if action == 0:
                dashboard.views.profile_wizard.assert_called_once_with("web_dev")
            elif action == 1:
                dashboard.views.delete_profile.assert_called_once_with("web_dev")

    def test_dashboard_shell_agent_settings_and_detail_scroll(self):
        case = test_dashboard.DashboardTests()
        dashboard = case.dashboard(
            [
                "a",
                "o",
                curses.KEY_NPAGE,
                curses.KEY_PPAGE,
                curses.KEY_LEFT,
                "\n",
                "\x1b",
            ]
        )
        with (
            patch.object(dashboard.ui, "external", side_effect=lambda action: action()),
            patch.object(dashboard.app, "run_agent", return_value="") as agent,
            patch.object(dashboard.app, "shell", return_value="") as shell,
            patch.object(dashboard.ui, "notice") as notice,
        ):
            dashboard.run()
        agent.assert_called_once_with("website", "claude")
        shell.assert_called_once_with("website")
        self.assertEqual(notice.call_args.args[0], "Workspace settings")
        for error in (Cancelled(), BrigError("failed")):
            dashboard = case.dashboard(["c", "\x1b"])
            dashboard.views.project_wizard.side_effect = error
            with patch.object(dashboard.ui, "notice") as notice:
                dashboard.run()
            self.assertEqual(notice.called, isinstance(error, BrigError))

    def test_dashboard_theme_color_support_and_fallback(self):
        ui = test_tui.TerminalTests().terminal([])
        for error in (None, curses.error()):
            with (
                patch.dict("os.environ", {}, clear=True),
                patch(
                    "brig.ui.tui.dashboard_render.curses.has_colors", return_value=True
                ),
                patch(
                    "brig.ui.tui.dashboard_render.curses.use_default_colors",
                    side_effect=error,
                ),
                patch("brig.ui.tui.dashboard_render.curses.init_pair") as colors,
                patch("brig.ui.tui.dashboard_render.curses.color_pair", return_value=0),
            ):
                renderer = DashboardRenderer(ui)
                self.assertTrue(renderer.styles["running"] & curses.A_BOLD)
                self.assertEqual(
                    colors.call_args_list[0].args[-1],
                    -1 if error is None else curses.COLOR_BLACK,
                )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("brig.ui.tui.dashboard_render.curses.has_colors", return_value=True),
            patch("brig.ui.tui.dashboard_render.curses.use_default_colors"),
            patch(
                "brig.ui.tui.dashboard_render.curses.init_pair",
                side_effect=curses.error,
            ),
        ):
            self.assertEqual(DashboardRenderer(ui).styles["focus"], ui.accent)
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("brig.ui.tui.dashboard_render.curses.has_colors", return_value=False),
        ):
            renderer = DashboardRenderer(ui)
            self.assertEqual(renderer.styles["focus"], ui.accent)
        with (
            patch.dict("os.environ", {"NO_COLOR": ""}),
            patch("brig.ui.tui.dashboard_render.curses.has_colors") as has_colors,
        ):
            self.assertEqual(DashboardRenderer(ui).styles["focus"], ui.accent)
            has_colors.assert_not_called()
        with patch("brig.ui.tui.terminal.locale.getencoding", return_value="ascii"):
            renderer.box(1, 1, 3, 10)
        self.assertTrue(any("+--------+" in row for row in ui.screen.written))
