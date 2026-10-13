"""Flow tests using scripted user choices rather than a real terminal."""

import curses
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from brig.application import Application
from brig.components.catalog import COMPONENTS
from brig.components.versions import LiveVersionCatalog
from brig.docker.dockerfile import render_dockerfile
from brig.errors import BrigError, Cancelled
from brig.ui.tui import InteractiveApp, Terminal
from tests.demo_engine import DemoEngine
from tests.fakes import FakeVersionCatalog, MemoryStore, demo_state


def node_release_source(url):
    if url.endswith("library/node"):
        return "Tags: 26.1.0, 24.2.0, 22.1.0\nArchitectures: amd64"
    if url == "https://nodejs.org/dist/index.json":
        return json.dumps(
            [
                {"version": "v26.1.0", "lts": False},
                {"version": "v24.2.0", "lts": "Krypton"},
                {"version": "v22.1.0", "lts": "Jod"},
            ]
        )
    if url == "https://registry.npmjs.org/npm":
        return json.dumps(
            {
                "versions": {
                    "12.0.0": {
                        "dist": {"tarball": "url"},
                        "engines": {"node": ">=24.0.0"},
                    }
                }
            }
        )
    raise AssertionError(f"Unexpected source: {url}")


class ScriptedTerminal:
    def __init__(self, *, inputs=(), multiples=(), choices=(), confirmed=True):
        self.inputs = iter(inputs)
        self.multiples = iter(multiples)
        self.choices = iter(choices)
        self.confirmed = confirmed
        self.messages = []
        self.selections = []
        self.version_choices = []

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
                    if option == name
                    or option.startswith(f"{name} · ")
                    or (
                        name in COMPONENTS
                        and option.startswith(
                            f"{COMPONENTS[name].category} · {COMPONENTS[name].label}"
                        )
                    )
                ),
                name,
            )
            for name in (
                next(self.multiples, ["claude"])
                if "· agents" in title
                else next(self.multiples)
            )
        ]

    def loading(self, message):
        self.messages.append(("Loading", [message]))

    def choose(self, *args, **kwargs):
        if args[0] == "Base profile":
            # Existing flow fixtures create standalone profiles unless explicitly
            # testing inheritance with a terminal that selects a base.
            return 0
        self.version_choices.append((args, kwargs))
        return next(self.choices)

    def confirm(self, *args, **kwargs):
        return self.confirmed

    def notice(self, title, lines, *, error=False):
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

    def test_playwright_is_visible_but_optional_without_node(self):
        for runtime in ("python", "php"):
            with self.subTest(runtime=runtime):
                catalog = FakeVersionCatalog()
                self.app.catalog_factory = lambda catalog=catalog: catalog
                terminal = ScriptedTerminal(
                    inputs=[f"{runtime}-browser-options"],
                    multiples=[[runtime], [], []],
                    choices=[0],
                )
                InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
                _, options, defaults = terminal.selections[1]
                playwright = next(
                    option for option in options if "Playwright" in option
                )
                self.assertIn("also installs Node.js (required)", playwright)
                self.assertNotIn(playwright, defaults)
                configuration = self.app.profile(f"{runtime}-browser-options").latest
                self.assertEqual(list(configuration.runtimes), [runtime])
                self.assertNotIn("playwright", configuration.tools)
                self.assertNotIn("node", catalog.calls)
                self.assertNotIn("playwright", catalog.calls)

    def test_playwright_adds_node_and_filters_versions_for_python_profile(self):
        def source(url):
            if url.endswith("library/python"):
                return "Tags: 3.14.8\nArchitectures: amd64"
            if url == "https://registry.npmjs.org/playwright":
                return json.dumps(
                    {
                        "versions": {
                            "1.50.1": {
                                "dist": {"tarball": "url"},
                                "engines": {"node": ">=22"},
                            },
                            "1.51.1": {
                                "dist": {"tarball": "url"},
                                "engines": {"node": ">=26"},
                            },
                        }
                    }
                )
            return node_release_source(url)

        self.app.catalog_factory = lambda: LiveVersionCatalog(source)
        terminal = ScriptedTerminal(
            inputs=["python-browser"],
            multiples=[["python"], ["playwright"], []],
            choices=[0, 1, 0],
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        configuration = self.app.profile("python-browser").latest
        self.assertEqual(configuration.runtimes, {"python": "3.14.8", "node": "24.2.0"})
        self.assertEqual(configuration.tools, {"playwright": "1.50.1"})
        self.assertEqual(terminal.version_choices[2][0][1], ["1.50.1 · Stable"])
        explanation = next(
            lines for title, lines in terminal.messages if "requires Node.js" in title
        )
        self.assertTrue(any("will also be installed" in line for line in explanation))
        with tempfile.TemporaryDirectory() as folder:
            project = self.app.create_project(
                "python-browser-project", Path(folder), "python-browser"
            )
            dockerfile = render_dockerfile(project)
        self.assertIn("FROM python:3.14.8-bookworm", dockerfile)
        self.assertIn("FROM node:24.2.0-bookworm AS node_runtime", dockerfile)
        self.assertIn("npm install --global playwright@1.50.1", dockerfile)

    def test_playwright_reuses_selected_node_without_another_version_prompt(self):
        terminal = ScriptedTerminal(
            inputs=["node-browser"],
            multiples=[["node"], ["playwright"], []],
            choices=[1, 0],
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(
            self.app.profile("node-browser").latest.runtimes, {"node": "20.18.2"}
        )
        self.assertEqual(len(terminal.version_choices), 2)
        self.assertFalse(
            any(
                "also installs Node.js" in option
                for option in terminal.selections[1][1]
            )
        )
        self.assertFalse(
            any("requires Node.js" in title for title, _ in terminal.messages)
        )

    def test_cancelling_added_node_version_keeps_state_unchanged(self):
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal(
            inputs=["cancel-browser"],
            multiples=[["python"], ["playwright"]],
            choices=[0],
        )
        choose = terminal.choose

        def cancel_node(title, *args, **kwargs):
            if title.startswith("Node.js version"):
                raise Cancelled
            return choose(title, *args, **kwargs)

        terminal.choose = cancel_node
        with self.assertRaises(Cancelled):
            InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(self.app.state, before)

    def test_declining_review_does_not_save_added_node_or_playwright(self):
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal(
            inputs=["declined-browser"],
            multiples=[["python"], ["playwright"], []],
            choices=[0, 0, 0],
            confirmed=False,
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(self.app.state, before)

    def test_project_deletion_can_cancel_then_confirm(self):
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal(confirmed=False)
        interactive = InteractiveApp(self.app, terminal, Path("/tmp"))
        self.assertFalse(interactive.delete_project("website"))
        self.assertEqual(self.app.state, before)
        terminal.confirmed = True
        self.assertTrue(interactive.delete_project("website"))
        self.assertNotIn(
            "website", [project.name for project in self.app.state.projects]
        )
        self.assertEqual(terminal.messages[-1][0], "Project deleted")

    def test_project_detail_returns_after_deletion_including_running_projects(self):
        terminal = ScriptedTerminal(choices=[7])
        InteractiveApp(self.app, terminal, Path("/tmp")).project_detail("website")
        self.assertNotIn(
            "website", [project.name for project in self.app.state.projects]
        )
        InteractiveApp(self.app, ScriptedTerminal(), Path("/tmp")).delete_project("api")
        self.assertEqual(self.app.state.projects, [])

    def test_project_deletion_requires_confirmation(self):
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal(confirmed=False)
        InteractiveApp(self.app, terminal, Path("/tmp")).delete_project("website")
        self.assertEqual(self.app.state, before)

    def test_project_detail_renames_and_reopens_under_the_new_name(self):
        terminal = ScriptedTerminal(inputs=["site"])
        with patch.object(terminal, "choose", side_effect=[6, Cancelled()]) as choose:
            InteractiveApp(self.app, terminal, Path("/tmp")).project_detail("website")
        self.assertIn("site", [project.name for project in self.app.state.projects])
        self.assertTrue(choose.call_args.args[0].startswith("site · "))

    def test_profile_rename_from_profile_list(self):
        terminal = ScriptedTerminal(inputs=["web"])
        with (
            patch.object(terminal, "choose", side_effect=[2, Cancelled()]),
            patch("brig.ui.tui.profiles.choose_list", side_effect=[0, Cancelled()]),
        ):
            InteractiveApp(self.app, terminal, Path("/tmp")).profiles()
        self.assertEqual(terminal.messages[-1][0], "Profile renamed")
        self.assertIn("web", [profile.name for profile in self.app.state.profiles])

    def test_project_detail_previews_dockerfile_without_mutating_project(self):
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal()
        with patch.object(terminal, "choose", side_effect=[8, Cancelled()]):
            InteractiveApp(self.app, terminal, Path("/tmp")).project_detail("website")
        title, lines = terminal.messages[-1]
        self.assertEqual(title, "Generated Dockerfile")
        self.assertIn("FROM php:8.3.15-cli-bookworm", "\n".join(lines))
        self.assertEqual(self.app.state, before)

    def test_profile_delete_requires_confirmation(self):
        self.app.save_profile("unused", {"php": "8.3.15"}, {}, {})
        before = deepcopy(self.app.state)
        terminal = ScriptedTerminal(confirmed=False)
        InteractiveApp(self.app, terminal, Path("/tmp")).delete_profile("unused")
        self.assertEqual(self.app.state, before)
        terminal.confirmed = True
        InteractiveApp(self.app, terminal, Path("/tmp")).delete_profile("unused")
        self.assertNotIn(
            "unused", [profile.name for profile in self.app.state.profiles]
        )
        self.assertEqual(terminal.messages[-1][0], "Profile deleted")

    def test_profile_used_by_project_is_rejected_before_confirmation(self):
        from unittest.mock import Mock

        terminal = ScriptedTerminal()
        terminal.confirm = Mock(side_effect=AssertionError("Should not offer deletion"))
        with self.assertRaisesRegex(BrigError, "Used by projects: website"):
            InteractiveApp(self.app, terminal, Path("/tmp")).delete_profile("web_dev")
        terminal.confirm.assert_not_called()

    def test_default_is_lts_and_labels_do_not_enter_saved_versions(self):
        self.app.catalog_factory = lambda: LiveVersionCatalog(node_release_source)
        terminal = ScriptedTerminal(
            inputs=["lts"], multiples=[["node"], [], []], choices=[1, 0]
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        args, _kwargs = terminal.version_choices[0]
        self.assertEqual(args[1], ["26.1.0 · Current", "24.2.0 · LTS", "22.1.0 · LTS"])
        self.assertEqual(args[2], 1)
        self.assertEqual(self.app.profile("lts").latest.runtimes, {"node": "24.2.0"})

    def test_no_compatible_tool_returns_to_runtime_selection_and_keeps_name(self):
        from unittest.mock import Mock

        fetch = Mock(side_effect=node_release_source)
        self.app.catalog_factory = lambda: LiveVersionCatalog(fetch)
        terminal = ScriptedTerminal(
            inputs=["compatible"],
            multiples=[["node"], ["npm"], ["node"], ["npm"], []],
            choices=[2, 1, 0, 0],
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        profile = self.app.profile("compatible")
        self.assertEqual(profile.latest.runtimes, {"node": "24.2.0"})
        self.assertEqual(profile.latest.tools, {"npm": "12.0.0"})
        self.assertTrue(
            any(
                "No verified npm version" in " ".join(lines)
                for _, lines in terminal.messages
            )
        )
        self.assertEqual(fetch.call_count, 3)

    def test_incompatible_release_is_hidden_from_tool_selector(self):
        def source(url):
            if url == "https://registry.npmjs.org/npm":
                return json.dumps(
                    {
                        "versions": {
                            "12.0.0": {
                                "dist": {"tarball": "url"},
                                "engines": {"node": ">=24"},
                            },
                            "10.0.0": {
                                "dist": {"tarball": "url"},
                                "engines": {"node": ">=20"},
                            },
                        }
                    }
                )
            return node_release_source(url)

        self.app.catalog_factory = lambda: LiveVersionCatalog(source)
        terminal = ScriptedTerminal(
            inputs=["node22"], multiples=[["node"], ["npm"], []], choices=[2, 0, 0]
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(terminal.version_choices[1][0][1], ["10.0.0 · Stable"])
        self.assertEqual(self.app.profile("node22").latest.tools, {"npm": "10.0.0"})

    def test_duplicate_profile_name_can_be_corrected_in_name_screen(self):
        name_input = TerminalTests().terminal(
            [*" web_dev ", "\n", "\x15", *"laravel", "\n"]
        )
        terminal = ScriptedTerminal(multiples=[["php"], [], []], choices=[0, 0])
        terminal.input = name_input.input
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(self.app.profile("laravel").latest.runtimes, {"php": "8.3.15"})
        errors = [
            (text, style)
            for text, style in name_input.screen.drawn
            if "already exists" in text
        ]
        self.assertTrue(errors)
        self.assertTrue(
            all(
                style & curses.A_BOLD and not style & curses.A_DIM
                for _, style in errors
            )
        )

    def test_profile_kebab_case_error_can_be_corrected_before_runtime_selection(self):
        name_input = TerminalTests().terminal(
            [*"Laravel Dev", "\n", "\x15", *"laravel-dev", "\n"]
        )
        terminal = ScriptedTerminal(multiples=[["php"], [], []], choices=[0, 0])
        terminal.input = name_input.input
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(self.app.profile("laravel-dev").name, "laravel-dev")
        self.assertTrue(
            any("name (kebab-case)" in text for text in name_input.screen.written)
        )
        self.assertTrue(
            any("Use kebab-case" in text for text in name_input.screen.written)
        )

    def test_project_kebab_case_error_and_duplicate_name_can_be_corrected_inline(self):
        with tempfile.TemporaryDirectory() as folder:
            name_input = TerminalTests().terminal(
                [
                    *"Laravel Project",
                    "\n",
                    "\x15",
                    *"website",
                    "\n",
                    "\x15",
                    *"laravel-project",
                    "\n",
                ]
            )
            terminal = ScriptedTerminal(inputs=[folder], choices=[0])
            scripted_input = terminal.input
            terminal.input = lambda title, *args, **kwargs: (
                name_input.input(title, *args, **kwargs)
                if "1/4" in title
                else scripted_input(title, *args, **kwargs)
            )
            InteractiveApp(self.app, terminal, Path("/tmp")).project_wizard()
            self.assertEqual(self.app.project("laravel-project").path, folder)
            self.assertTrue(
                any("name (kebab-case)" in text for text in name_input.screen.written)
            )
            self.assertTrue(
                any("Use kebab-case" in text for text in name_input.screen.written)
            )
            self.assertTrue(
                any("already exists" in text for text in name_input.screen.written)
            )

    def test_duplicate_name_can_cancel_before_component_selection(self):
        before = deepcopy(self.app.state)
        name_input = TerminalTests().terminal([*"web_dev", "\n", "\x1b"])
        terminal = ScriptedTerminal()
        terminal.input = name_input.input
        with self.assertRaises(Cancelled):
            InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(terminal.selections, [])
        self.assertEqual(self.app.state, before)

    def test_empty_runtime_selection_keeps_wizard_open_and_preserves_name(self):
        selector = TerminalTests().terminal(
            ["\n", curses.KEY_DOWN, " ", "\n", "\n", "\n", "\n"]
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
        self.assertTrue(any("Browser automation" in option for option in tool_options))
        self.assertEqual(len(tool_options), 4)
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
        from unittest.mock import Mock

        from brig.components.versions import LiveVersionCatalog

        fetch = Mock(return_value="Tags: 8.3.1\nArchitectures: amd64")
        self.app.catalog_factory = lambda: LiveVersionCatalog(fetch)
        terminal = ScriptedTerminal(
            inputs=["php-only"], multiples=[["php"], [], []], choices=[0, 0]
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard()
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(fetch.call_args.args[0].endswith("/php"))

    def test_retry_continues_same_wizard_without_saving_partial_profile(self):
        from unittest.mock import Mock
        from urllib.error import URLError

        from brig.components.versions import LiveVersionCatalog

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
        original = deepcopy(self.app.profile("python_dev").latest)
        projects = deepcopy(self.app.state.projects)
        self.app.catalog_factory = lambda: FakeVersionCatalog(
            {"python": ("3.14.0",), "uv": ("0.10.0",), "redis": ("8.0.1",)}
        )
        terminal = ScriptedTerminal(
            multiples=[["python"], ["uv"], ["redis"]], choices=[0, 0, 0, 0]
        )
        InteractiveApp(self.app, terminal, Path("/tmp")).profile_wizard("python_dev")
        self.assertEqual(self.app.profile("python_dev").latest.number, 3)
        self.assertEqual(self.app.profile("python_dev").versions[1], original)
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
            self.assertEqual(project.profile, "web_dev")

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
        self.drawn = []
        self.positions = []

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
        self.drawn.append((value[:maximum], style))
        self.positions.append((y, x, value[:maximum]))


class TerminalTests(unittest.TestCase):
    def terminal(self, keys, size=(24, 90)):
        terminal = Terminal.__new__(Terminal)
        terminal.screen = FakeScreen(keys, size)
        terminal.accent = 0
        terminal.error_style = curses.A_BOLD
        return terminal

    def test_arrow_navigation_selects_option(self):
        terminal = self.terminal([curses.KEY_DOWN, "\n"])
        self.assertEqual(terminal.choose("Menu", ["one", "two"]), 1)

    def test_save_is_default_and_delete_defaults_to_cancel(self):
        terminal = self.terminal(["\n", "\n"])
        self.assertTrue(terminal.confirm("Create profile", ["Name: custom"]))
        terminal = self.terminal(["\n", "\n"])
        self.assertFalse(
            terminal.confirm(
                "Delete profile", ["Name: custom"], action="Delete profile"
            )
        )
        terminal = self.terminal(["\n", curses.KEY_UP, "\n"])
        self.assertTrue(
            terminal.confirm(
                "Delete profile", ["Name: custom"], action="Delete profile"
            )
        )

    def test_validation_error_has_dedicated_line_and_keeps_keyboard_help(self):
        terminal = self.terminal(["\n", " ", "\n"])
        self.assertEqual(
            terminal.multiple(
                "Runtimes",
                ["php"],
                set(),
                required_message="Select at least one runtime.",
            ),
            ["php"],
        )
        self.assertIn(
            ("Error: Select at least one runtime.", curses.A_BOLD),
            terminal.screen.drawn,
        )
        self.assertTrue(
            any(
                "space toggle" in text and style == curses.A_DIM
                for text, style in terminal.screen.drawn
            )
        )

    def test_color_terminal_initializes_red_bold_error_style(self):
        from unittest.mock import Mock, patch

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("brig.ui.tui.terminal.curses.curs_set"),
            patch("brig.ui.tui.terminal.curses.has_colors", return_value=True),
            patch("brig.ui.tui.terminal.curses.start_color"),
            patch("brig.ui.tui.terminal.curses.use_default_colors"),
            patch("brig.ui.tui.terminal.curses.init_pair") as init_pair,
            patch(
                "brig.ui.tui.terminal.curses.color_pair",
                side_effect=lambda number: number << 8,
            ),
        ):
            terminal = Terminal(Mock())
        init_pair.assert_any_call(2, curses.COLOR_RED, -1)
        self.assertEqual(terminal.error_style, curses.A_BOLD | (2 << 8))

    def test_no_color_keeps_terminal_usable_without_initializing_colors(self):
        from unittest.mock import Mock

        with (
            patch.dict("os.environ", {"NO_COLOR": ""}),
            patch("brig.ui.tui.terminal.curses.curs_set"),
            patch("brig.ui.tui.terminal.curses.start_color") as start_color,
        ):
            terminal = Terminal(Mock())
        start_color.assert_not_called()
        self.assertEqual(terminal.accent, curses.A_BOLD)

    def test_color_initialization_failure_falls_back_to_basic_attributes(self):
        from unittest.mock import Mock

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("brig.ui.tui.terminal.curses.curs_set"),
            patch("brig.ui.tui.terminal.curses.has_colors", return_value=True),
            patch("brig.ui.tui.terminal.curses.start_color", side_effect=curses.error),
        ):
            terminal = Terminal(Mock())
        self.assertEqual(terminal.error_style, curses.A_BOLD)

    def test_minimum_size_keeps_selection_error_and_keyboard_help_separate(self):
        terminal = self.terminal([], size=(12, 45))
        terminal.render(
            "Runtimes",
            ["python", "php", "node"],
            "↑↓ move · space toggle · enter next · esc back",
            selected=2,
            error_message="Select a runtime.",
        )
        positions = terminal.screen.positions
        selected_y = next(y for y, _, text in positions if "› node" in text)
        error_y = next(y for y, _, text in positions if "Error:" in text)
        help_y = next(y for y, _, text in positions if "space toggle" in text)
        self.assertLess(selected_y, error_y)
        self.assertLess(error_y, help_y)
        self.assertTrue(any("esc back" in text for _, _, text in positions))
        self.assertTrue(any("2-3 / 3" in text for _, _, text in positions))

    def test_ascii_locale_uses_readable_navigation_symbols(self):
        terminal = self.terminal([], size=(12, 45))
        with patch("brig.ui.tui.terminal.locale.getencoding", return_value="ascii"):
            terminal.render("Menu", ["Python"], "↑↓ move · enter select", selected=0)
        self.assertTrue(any("> Python" in text for text in terminal.screen.written))
        self.assertTrue(any("up/down move" in text for text in terminal.screen.written))
        for text in terminal.screen.written:
            text.encode("ascii")

    def test_notice_can_scroll_to_last_line_on_minimum_terminal(self):
        terminal = self.terminal([curses.KEY_DOWN] * 20 + ["\n"], size=(12, 45))
        terminal.notice("Details", [f"Line {number}" for number in range(20)])
        self.assertIn("  Line 19", terminal.screen.written)

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
