"""Interactive project registration and environment actions."""

from pathlib import Path

from brig.application import Application
from brig.components.agents import AGENTS
from brig.errors import BrigError, Cancelled
from brig.ui.listings import list_records
from brig.ui.presentation import configuration_lines, project_lines
from brig.ui.tui.browser import choose_card
from brig.ui.tui.terminal import Terminal


class ProjectViews:
    def __init__(self, app: Application, terminal: Terminal, data_directory: Path):
        self.app = app
        self.ui = terminal
        self.data_directory = data_directory

    def project_wizard(self) -> None:
        if not self.app.state.profiles:
            raise BrigError("Create a profile before registering a project.")
        name = self.ui.input(
            "Create project · 1/4 · name (kebab-case)",
            required_message="Project name is required. Enter a name to continue.",
            validator=self.app.validate_project_name,
        )
        folder = self.ui.input(
            "Create project · 2/4 · existing local folder", str(Path.cwd())
        )
        profiles = self.app.state.profiles
        selection = self.ui.choose(
            "Create project · 3/4 · profile",
            [f"{p.name} · version {p.latest.number}" for p in profiles],
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
            "Project saved",
            [
                f"{project.name} is ready. Use 'brig run {project.name}' to start and enter it."
            ],
        )

    def projects(self) -> None:
        selected = 0
        while True:
            try:
                projects = self.app.state.projects
                records = list_records(self.app, "project") + [("+ Create project", [])]
                index = choose_card(
                    self.ui, "Projects", records, min(selected, len(records) - 1)
                )
                selected = index
                if index == len(projects):
                    self.project_wizard()
                else:
                    self.project_detail(projects[index].name)
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice("Could not complete action", [str(error)], error=True)

    def delete_project(self, name: str) -> bool:
        project = self.app.project_for_deletion(name)
        if not self.ui.confirm(
            f"Delete project '{project.name}'",
            [
                f"Name       {project.name}",
                f"Folder     {project.path or '(none)'}",
                f"Profile    {project.profile}",
                "Only the Brig registration will be deleted.",
                "Your local folder, code, and profile will be kept.",
            ],
            action="Delete project",
        ):
            return False
        self.ui.notice("Project deleted", [self.app.delete_project(project.name)])
        return True

    def project_detail(self, name: str) -> None:
        while True:
            try:
                project = self.app.project(name)
                choice = self.ui.choose(
                    f"{name} · {self.app.project_status(project)}",
                    [
                        "View configuration and environment",
                        "Start",
                        "Stop",
                        "Run agent",
                        "Shell",
                        "Apply profile update",
                        "Delete project",
                        "View Dockerfile",
                    ],
                )
                if choice == 0:
                    self.ui.notice(name, project_lines(self.app, project))
                    continue
                if choice == 1:
                    message = getattr(self.ui, "external", lambda action: action())(
                        lambda: self.app.start(name)
                    )
                elif choice == 2:
                    message = getattr(self.ui, "external", lambda action: action())(
                        lambda: self.app.stop(name)
                    )
                elif choice == 3:
                    agents = project.configuration.selected_agents
                    selected = self.ui.choose(
                        "Run agent",
                        [AGENTS[agent].name for agent in agents],
                    )
                    message = getattr(self.ui, "external", lambda action: action())(
                        lambda agent=agents[selected]: self.app.run_agent(name, agent)
                    )
                elif choice == 4:
                    message = getattr(self.ui, "external", lambda action: action())(
                        lambda: self.app.shell(name)
                    )
                elif choice == 5:
                    latest = self.app.profile(project.profile).latest
                    if not self.ui.confirm(
                        "Apply profile update",
                        [
                            f"Current version: {project.configuration.number}",
                            *configuration_lines(latest),
                            "Stop the project before applying an update.",
                        ],
                    ):
                        continue
                    message = self.app.update_project(name)
                elif choice == 6:
                    if self.delete_project(name):
                        return
                    continue
                else:
                    self.ui.notice(
                        "Generated Dockerfile",
                        self.app.project_dockerfile(name, Path.cwd()).splitlines(),
                    )
                    continue
                if message:
                    self.ui.notice("Result", message.splitlines())
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice("Could not complete action", [str(error)], error=True)
