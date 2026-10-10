"""Top-level TUI navigation and curses lifecycle."""

import curses
from pathlib import Path

from brig.application import Application
from brig.errors import BrigError, Cancelled
from brig.ui.tui.dashboard import Dashboard
from brig.ui.tui.profiles import ProfileViews
from brig.ui.tui.projects import ProjectViews
from brig.ui.tui.terminal import Terminal


class InteractiveApp:
    def __init__(self, app: Application, terminal: Terminal, data_directory: Path):
        self.app = app
        self.ui = terminal
        self.data_directory = data_directory
        self.profile_views = ProfileViews(app, terminal, data_directory)
        self.project_views = ProjectViews(app, terminal, data_directory)

    def home(self) -> None:
        Dashboard(self.app, self.ui, self.data_directory, self).run()

    def profiles(self) -> None:
        self.profile_views.profiles()

    def profile_wizard(self, name: str | None = None, **options) -> None:
        self.profile_views.profile_wizard(name, **options)

    def delete_profile(self, name: str) -> None:
        self.profile_views.delete_profile(name)

    def projects(self) -> None:
        self.project_views.projects()

    def project_wizard(self) -> None:
        self.project_views.project_wizard()

    def project_detail(self, name: str) -> None:
        self.project_views.project_detail(name)

    def delete_project(self, name: str) -> bool:
        return self.project_views.delete_project(name)


def launch(
    app: Application,
    directory: Path,
    action: str = "home",
    name: str | None = None,
    *,
    base: str | None = None,
    base_version: int | None = None,
    update_base: bool = False,
) -> bool:
    def run(screen):
        interactive = InteractiveApp(app, Terminal(screen), directory)
        try:
            if action in ("profile-list", "project-list"):
                Dashboard(app, interactive.ui, directory).run(
                    "Profiles" if action == "profile-list" else "Projects",
                    read_only=True,
                )
            elif action == "profile-create":
                if base is not None or base_version is not None:
                    interactive.profile_wizard(base=base, base_version=base_version)
                else:
                    interactive.profile_wizard()
            elif action == "profile-edit":
                if update_base:
                    interactive.profile_wizard(name, update_base=True)
                else:
                    interactive.profile_wizard(name)
            elif action == "profile-delete":
                interactive.delete_profile(name)
            elif action == "project-create":
                interactive.project_wizard()
            elif action == "project-delete":
                interactive.delete_project(name)
            else:
                interactive.home()
        except Cancelled:
            pass
        except BrigError as error:
            interactive.ui.notice("Could not complete action", [str(error)], error=True)
            return False
        return True

    return curses.wrapper(run)
