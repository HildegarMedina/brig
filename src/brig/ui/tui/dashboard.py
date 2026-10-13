"""Workspace navigation and dashboard actions, sharing existing application flows."""

import curses
from functools import partial
from pathlib import Path

from brig.application import Application
from brig.errors import BrigError, Cancelled
from brig.i18n import LANGUAGES, current_language, resolve_language, set_language, tr
from brig.i18n.preferences import load_language, save_language
from brig.models import Project
from brig.ui.agent_selection import choose_agent
from brig.ui.presentation import configuration_lines, project_lines
from brig.ui.tui.dashboard_render import DashboardItem, DashboardRenderer
from brig.ui.tui.terminal import Terminal


class Dashboard:
    sections = ("Projects", "Profiles", "Settings")

    def __init__(self, app: Application, ui: Terminal, directory: Path, views=None):
        self.app, self.ui, self.directory, self.views = app, ui, directory, views
        self.renderer = DashboardRenderer(ui)

    def items(self, section: str) -> list[DashboardItem]:
        if section == "Projects":
            return [self.project_item(project) for project in self.app.state.projects]
        if section == "Profiles":
            return [
                DashboardItem(
                    profile.name,
                    tr("version {value0}").format(value0=profile.latest.number),
                    ", ".join(profile.latest.runtimes),
                    tr("{value0} saved versions").format(value0=len(profile.versions)),
                    configuration_lines(profile.latest),
                )
                for profile in self.app.state.profiles
            ]
        return [
            DashboardItem(
                tr("Workspace settings"),
                tr("local"),
                tr("Docker Compose"),
                str(self.directory),
                [
                    tr("Engine     {value0}").format(
                        value0="Demo" if self.app.engine.simulated else "Docker Compose"
                    ),
                    tr("Data       {value0}").format(value0=self.directory),
                    tr("Language   {language}").format(
                        language=LANGUAGES[current_language()]
                    ),
                    "",
                    tr("Profiles pin published runtime and tool versions."),
                    tr("Project updates are explicit; stop before applying them."),
                    tr("NO_COLOR disables color. Esc responds in 100 ms."),
                ],
            )
        ]

    def project_item(self, project: Project) -> DashboardItem:
        status = self.app.project_status(project)
        return DashboardItem(
            project.name,
            status,
            tr("{value0} · version {value1}").format(
                value0=project.profile, value1=project.configuration.number
            ),
            project.path or tr("No folder mounted"),
            project_lines(self.app, project, status=status),
        )

    def open(self, section: str, item: DashboardItem, read_only: bool):
        if read_only:
            self.ui.notice(item.name, item.details)
        elif section == "Settings":
            saved = load_language(self.directory)
            codes = ["auto", *LANGUAGES]
            selected = self.ui.choose(
                tr("Interface language"),
                [tr("Automatic"), *LANGUAGES.values()],
                default=codes.index(saved or "auto"),
            )
            code = codes[selected]
            save_language(self.directory, code)
            set_language(resolve_language(saved=None if code == "auto" else code))
        elif section == "Projects":
            self.views.project_detail(item.name)
        else:
            try:
                action = self.ui.choose(
                    item.name,
                    [
                        tr("Edit profile"),
                        tr("Rename profile"),
                        tr("Delete profile"),
                        tr("Back"),
                    ],
                )
                if action == 0:
                    self.views.profile_wizard(item.name)
                elif action == 1:
                    self.views.rename_profile(item.name)
                elif action == 2:
                    self.views.delete_profile(item.name)
            except Cancelled:
                pass

    def act(self, key, section: str, item: DashboardItem | None):
        if key == "c" and section in ("Projects", "Profiles"):
            if section == "Projects":
                self.views.project_wizard()
            else:
                self.views.profile_wizard()
        elif item and section == "Projects" and key in ("s", "a", "o"):
            project = self.app.project(item.name)
            if key == "s":
                action = partial(
                    self.app.stop if item.status == "running" else self.app.start,
                    item.name,
                )
            elif key == "a":
                action = partial(
                    self.app.run_agent,
                    item.name,
                    choose_agent(project, terminal=self.ui),
                )
            else:
                action = partial(
                    self.app.shell,
                    item.name,
                    agent=choose_agent(project, terminal=self.ui),
                )
            self.ui.external(action)

    def run(self, section: str = "Projects", *, read_only=False):
        tab = self.sections.index(section)
        positions = {name: 0 for name in self.sections}
        detail_offset = 0
        items = self.items(section)
        while True:
            selected = min(positions[section], max(0, len(items) - 1))
            positions[section] = selected
            footer = (
                tr("↑↓ move · Enter details · Esc exit · r refresh")
                if read_only
                else (
                    tr(
                        "←→ tabs · ↑↓ move · Enter actions · c create · r refresh · Esc exit"
                    )
                )
            )
            if not read_only and section == "Projects":
                footer = tr(
                    "←→ tabs · ↑↓ move · Enter actions · c new · s start/stop · a agent · o shell · r refresh · Esc exit"
                )
            self.renderer.draw(
                list(self.sections),
                tab,
                items,
                selected,
                detail_offset,
                footer,
                read_only=read_only,
            )
            key = self.ui.key()
            if key in ("\x1b", "q"):
                return
            if key in (curses.KEY_UP, "k", curses.KEY_DOWN, "j") and items:
                positions[section] = (
                    selected + (-1 if key in (curses.KEY_UP, "k") else 1)
                ) % len(items)
                detail_offset = 0
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, "\t") and not read_only:
                tab = (tab + (-1 if key == curses.KEY_LEFT else 1)) % len(self.sections)
                section = self.sections[tab]
                items = self.items(section)
                detail_offset = 0
            elif key in (curses.KEY_NPAGE, curses.KEY_PPAGE) and items:
                page = max(1, self.ui.screen.getmaxyx()[0] - 17)
                maximum = max(0, len(items[selected].details) - page)
                detail_offset = max(
                    0,
                    min(
                        maximum,
                        detail_offset + (page if key == curses.KEY_NPAGE else -page),
                    ),
                )
            else:
                try:
                    item = items[selected] if items else None
                    if key in ("\n", "\r", curses.KEY_ENTER) and item:
                        self.open(section, item, read_only)
                    elif not read_only:
                        self.act(key, section, item)
                    if key in ("r", "c", "s", "a", "o", "\n", "\r", curses.KEY_ENTER):
                        items = self.items(section)
                        detail_offset = 0
                except Cancelled:
                    pass
                except BrigError as error:
                    self.ui.notice(
                        tr("Could not complete action"), [str(error)], error=True
                    )
