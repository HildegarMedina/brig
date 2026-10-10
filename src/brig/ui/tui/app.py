"""Top-level TUI navigation and curses lifecycle."""

import curses
from pathlib import Path

from brig.application import Application
from brig.components.agents import AGENTS
from brig.errors import BrigError, Cancelled
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
                            f"{agent.name}: {'installed in project images' if agent.available else 'future integration'}"
                            for agent in AGENTS.values()
                        ]
                        + [
                            "",
                            "Agents will run inside each project's development container.",
                            "Sign in or connect a provider from each agent on first use.",
                        ],
                    )
                elif choice == 3:
                    self.ui.notice(
                        "Settings",
                        [
                            "Language: English",
                            f"Engine: {'Demo' if self.app.engine.simulated else 'Docker Compose'}",
                            f"Data directory: {self.data_directory}",
                            "Catalog: live versions from Docker Official Images, PyPI and npm",
                            "Project updates: explicit; stop the project before applying",
                        ],
                    )
                else:
                    return
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice("Could not complete action", [str(error)], error=True)

    def profiles(self) -> None:
        self.profile_views.profiles()

    def profile_wizard(self, name: str | None = None) -> None:
        self.profile_views.profile_wizard(name)

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
    app: Application, directory: Path, action: str = "home", name: str | None = None
) -> bool:
    def run(screen):
        interactive = InteractiveApp(app, Terminal(screen), directory)
        try:
            if action == "profile-create":
                interactive.profile_wizard()
            elif action == "profile-edit":
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
