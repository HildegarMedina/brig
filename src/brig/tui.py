"""Curses views and interactive flows; all mutations go through Application."""

import curses
from pathlib import Path

from brig.application import Application
from brig.catalog import AGENTS, RUNTIMES, SERVICES, TOOLS
from brig.errors import BrigError, Cancelled
from brig.models import ProfileRevision
from brig.presentation import configuration_lines, project_lines


class Terminal:
    def __init__(self, screen):
        self.screen = screen
        screen.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.accent = curses.A_BOLD
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            self.accent |= curses.color_pair(1)

    def _write(self, y: int, x: int, text: str, style: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if 0 <= y < height and 0 <= x < width - 1:
            safe = "".join(c if c.isprintable() else " " for c in text)
            try:
                self.screen.addnstr(y, x, safe, width - x - 1, style)
            except curses.error:
                pass

    def render(
        self, title: str, rows: list[str], footer: str, selected: int = -1
    ) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self._write(1, 2, "brig", self.accent)
        self._write(1, 10, "DEMO MODE · no Docker or agents executed", curses.A_DIM)
        if height < 12 or width < 45:
            self._write(3, 1, "Resize terminal to at least 45 × 12.")
            self.screen.refresh()
            return
        self._write(3, 2, title, curses.A_BOLD)
        capacity = max(1, height - 8)
        offset = max(0, selected - capacity + 1)
        for index, row in enumerate(rows[offset : offset + capacity], offset):
            is_selected = index == selected
            self._write(
                5 + index - offset,
                2,
                ("› " if is_selected else "  ") + row,
                curses.A_REVERSE if is_selected else 0,
            )
        self._write(height - 2, 2, footer, curses.A_DIM)
        self.screen.refresh()

    def key(self):
        key = self.screen.get_wch()
        if key in ("\x03", "\x04"):
            raise KeyboardInterrupt
        return key

    def choose(
        self,
        title: str,
        options: list[str],
        default: int = 0,
        *,
        searchable: bool = False,
    ) -> int:
        if not options:
            raise BrigError("No options available.")
        selected = min(default, len(options) - 1)
        query = ""
        while True:
            indices = [
                i
                for i, value in enumerate(options)
                if query.casefold() in value.casefold()
            ]
            if selected not in indices and indices:
                selected = indices[0]
            position = indices.index(selected) if selected in indices else -1
            footer = "↑↓ navigate · enter select · esc back"
            if searchable:
                footer += " · / search"
            rows = [options[i] for i in indices] or [
                "No matches. Press / to change search."
            ]
            self.render(
                title + (f" · search: {query}" if query else ""), rows, footer, position
            )
            key = self.key()
            if key in ("\x1b", "q"):
                raise Cancelled
            if key in (curses.KEY_UP, "k") and indices:
                selected = indices[(position - 1) % len(indices)]
            elif key in (curses.KEY_DOWN, "j") and indices:
                selected = indices[(position + 1) % len(indices)]
            elif key in ("\n", "\r", curses.KEY_ENTER) and indices:
                return selected
            elif key == "/" and searchable:
                query = self.input("Search", query)

    def multiple(self, title: str, options: list[str], defaults: set[str]) -> list[str]:
        chosen = set(defaults)
        selected = 0
        while True:
            rows = [
                f"[{'x' if option in chosen else ' '}] {option}" for option in options
            ]
            self.render(
                title,
                rows,
                "↑↓ navigate · space toggle · enter continue · esc cancel",
                selected,
            )
            key = self.key()
            if key == "\x1b":
                raise Cancelled
            if key in (curses.KEY_UP, "k"):
                selected = (selected - 1) % len(options)
            elif key in (curses.KEY_DOWN, "j"):
                selected = (selected + 1) % len(options)
            elif key == " ":
                option = options[selected]
                chosen.symmetric_difference_update({option})
            elif key in ("\n", "\r", curses.KEY_ENTER):
                return [option for option in options if option in chosen]

    def input(self, title: str, default: str = "") -> str:
        value = default
        while True:
            self.render(
                title,
                [value + "▏"],
                "type to edit · ctrl+u clear · enter continue · esc cancel",
            )
            key = self.key()
            if key == "\x1b":
                raise Cancelled
            if key in ("\n", "\r", curses.KEY_ENTER):
                return value.strip()
            if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                value = value[:-1]
            elif key == "\x15":
                value = ""
            elif isinstance(key, str) and key.isprintable():
                value += key

    def notice(self, title: str, lines: list[str]) -> None:
        offset = 0
        while True:
            height, _ = self.screen.getmaxyx()
            maximum = max(0, len(lines) - max(1, height - 8))
            offset = min(offset, maximum)
            self.render(title, lines[offset:], "↑↓ scroll · enter / esc close")
            key = self.key()
            if key in ("\n", "\r", "\x1b", "q", curses.KEY_ENTER):
                return
            if key == curses.KEY_DOWN:
                offset = min(offset + 1, maximum)
            elif key == curses.KEY_UP:
                offset = max(offset - 1, 0)

    def confirm(self, title: str, lines: list[str]) -> bool:
        self.notice(title, lines)
        return self.choose("Save these changes?", ["Save", "Cancel"], default=1) == 0


class InteractiveApp:
    def __init__(self, app: Application, terminal: Terminal, data_directory: Path):
        self.app = app
        self.ui = terminal
        self.data_directory = data_directory

    def home(self) -> None:
        while True:
            try:
                choice = self.ui.choose(
                    "Your development workspace",
                    ["Projects", "Profiles", "Agents", "Settings", "Quit"],
                )
                if choice == 0:
                    self.projects()
                elif choice == 1:
                    self.profiles()
                elif choice == 2:
                    self.ui.notice(
                        "Agents",
                        [
                            f"{agent.name}: {'available (simulation)' if agent.available else 'future integration'}"
                            for agent in AGENTS.values()
                        ]
                        + [
                            "",
                            "Agents will run inside each project's development container.",
                            "No authentication is performed in this prototype.",
                        ],
                    )
                elif choice == 3:
                    self.ui.notice(
                        "Settings",
                        [
                            "Language: English",
                            "Engine: Demo",
                            f"Data directory: {self.data_directory}",
                            "Catalog: static demo versions; not a compatibility guarantee",
                            "Project updates: explicit; stop the project before applying",
                        ],
                    )
                else:
                    return
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice("Could not complete action", [str(error)])

    def _select_versions(
        self, title: str, catalog: dict, defaults: dict[str, str]
    ) -> dict[str, str]:
        if not catalog:
            return {}
        names = self.ui.multiple(title, list(catalog), set(defaults))
        result = {}
        for name in names:
            versions = list(catalog[name])
            default = (
                versions.index(defaults[name]) if defaults.get(name) in versions else 0
            )
            index = self.ui.choose(
                f"{name} version · demonstration catalog",
                versions,
                default,
                searchable=True,
            )
            result[name] = versions[index]
        return result

    def profile_wizard(self, name: str | None = None) -> None:
        editing = name is not None
        existing = self.app.profile(name).latest if editing else None
        title = "Edit profile" if editing else "Create profile"
        if not editing:
            name = self.ui.input(f"{title} · 1/6 · name")
        runtimes = self._select_versions(
            f"{title} · 2/6 · runtimes", RUNTIMES, existing.runtimes if existing else {}
        )
        if not runtimes:
            raise BrigError("Select at least one runtime. No changes were saved.")
        compatible_tools = {
            n: t.versions for n, t in TOOLS.items() if t.runtime in runtimes
        }
        tools = self._select_versions(
            f"{title} · 3/6 · tools",
            compatible_tools,
            {n: v for n, v in existing.tools.items() if n in compatible_tools}
            if existing
            else {},
        )
        services = self._select_versions(
            f"{title} · 4/6 · services", SERVICES, existing.services if existing else {}
        )
        self.ui.choose(f"{title} · 5/6 · default agent", ["Claude Code (simulated)"])
        revision = ProfileRevision(
            existing.number + 1 if existing else 1, runtimes, tools, services
        )
        if not self.ui.confirm(
            f"{title} · 6/6 · review",
            [
                f"Name       {name}",
                *configuration_lines(revision),
                "",
                "Existing projects keep their current revision.",
            ],
        ):
            return
        profile = self.app.save_profile(
            name, runtimes, tools, services, editing=editing
        )
        self.ui.notice(
            "Profile saved", [f"{profile.name} · revision {profile.latest.number}"]
        )

    def project_wizard(self) -> None:
        if not self.app.state.profiles:
            raise BrigError("Create a profile before registering a project.")
        name = self.ui.input("Create project · 1/4 · name")
        folder = self.ui.input(
            "Create project · 2/4 · existing local folder", str(Path.cwd())
        )
        profiles = self.app.state.profiles
        selection = self.ui.choose(
            "Create project · 3/4 · profile",
            [f"{p.name} · revision {p.latest.number}" for p in profiles],
        )
        profile = profiles[selection]
        if not self.ui.confirm(
            "Create project · 4/4 · review",
            [
                f"Name       {name}",
                f"Folder     {folder}",
                f"Profile    {profile.name}",
                *configuration_lines(profile.latest),
                "",
                "Each project has its own planned network, containers and volumes.",
            ],
        ):
            return
        project = self.app.create_project(name, Path(folder), profile.name)
        self.ui.notice(
            "Project saved", [f"{project.name} is ready to start (simulated)."]
        )

    def profiles(self) -> None:
        while True:
            try:
                profiles = self.app.state.profiles
                options = [
                    f"{p.name} · revision {p.latest.number}" for p in profiles
                ] + ["+ Create profile"]
                index = self.ui.choose("Profiles", options)
                if index == len(profiles):
                    self.profile_wizard()
                else:
                    name = profiles[index].name
                    if (
                        self.ui.choose(name, ["View latest revision", "Edit profile"])
                        == 0
                    ):
                        self.ui.notice(
                            name, configuration_lines(self.app.profile(name).latest)
                        )
                    else:
                        self.profile_wizard(name)
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice("Could not complete action", [str(error)])

    def projects(self) -> None:
        while True:
            try:
                projects = self.app.state.projects
                options = [
                    f"{p.name} · {p.profile} r{p.configuration.number} · {'running (simulated)' if p.running else 'stopped'}"
                    for p in projects
                ] + ["+ Create project"]
                index = self.ui.choose("Projects", options)
                if index == len(projects):
                    self.project_wizard()
                else:
                    self.project_detail(projects[index].name)
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice("Could not complete action", [str(error)])

    def project_detail(self, name: str) -> None:
        while True:
            try:
                project = self.app.project(name)
                choice = self.ui.choose(
                    f"{name} · {'running (simulated)' if project.running else 'stopped'}",
                    [
                        "View configuration and environment",
                        "Start",
                        "Stop",
                        "Run agent",
                        "Shell",
                        "Apply profile update",
                    ],
                )
                if choice == 0:
                    self.ui.notice(name, project_lines(self.app, project))
                    continue
                if choice == 1:
                    message = self.app.start(name)
                elif choice == 2:
                    message = self.app.stop(name)
                elif choice == 3:
                    agents = list(AGENTS)
                    selected = self.ui.choose(
                        "Run agent",
                        [
                            f"{agent.name} · {'simulation' if agent.available else 'coming later'}"
                            for agent in AGENTS.values()
                        ],
                    )
                    message = self.app.run_agent(name, agents[selected])
                elif choice == 4:
                    message = self.app.shell(name)
                else:
                    latest = self.app.profile(project.profile).latest
                    if not self.ui.confirm(
                        "Apply profile update",
                        [
                            f"Current revision: {project.configuration.number}",
                            *configuration_lines(latest),
                            "Stop the project before applying an update.",
                        ],
                    ):
                        continue
                    message = self.app.update_project(name)
                self.ui.notice("Demo result", message.splitlines())
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice("Could not complete action", [str(error)])


def launch(
    app: Application, directory: Path, action: str = "home", name: str | None = None
) -> bool:
    def run(screen):
        interactive = InteractiveApp(app, Terminal(screen), directory)
        try:
            if action == "profile-create":
                interactive.profile_wizard()
            elif action == "profile-edit":
                interactive.profile_wizard(name)
            elif action == "project-create":
                interactive.project_wizard()
            else:
                interactive.home()
        except Cancelled:
            pass
        except BrigError as error:
            interactive.ui.notice("Could not complete action", [str(error)])
            return False
        return True

    return curses.wrapper(run)
