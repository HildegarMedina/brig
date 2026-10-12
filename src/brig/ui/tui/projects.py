"""Interactive project registration and environment actions."""

from pathlib import Path

from brig.application import Application
from brig.errors import BrigError, Cancelled
from brig.i18n import tr
from brig.ui.agent_selection import choose_agent
from brig.ui.listings import list_rows
from brig.ui.presentation import configuration_lines, project_lines
from brig.ui.tui.browser import choose_list
from brig.ui.tui.terminal import Terminal


class ProjectViews:
    def __init__(self, app: Application, terminal: Terminal, data_directory: Path):
        self.app = app
        self.ui = terminal
        self.data_directory = data_directory

    def project_wizard(self) -> None:
        if not self.app.state.profiles:
            raise BrigError(tr("Create a profile before registering a project."))
        name = self.ui.input(
            tr("Create project · 1/4 · name (kebab-case)"),
            required_message=tr("Project name is required. Enter a name to continue."),
            validator=self.app.validate_project_name,
        )
        folder = self.ui.input(
            tr("Create project · 2/4 · existing local folder"), str(Path.cwd())
        )
        profiles = self.app.state.profiles
        selection = self.ui.choose(
            tr("Create project · 3/4 · profile"),
            [
                tr("{value0} · version {value1}").format(
                    value0=p.name, value1=p.latest.number
                )
                for p in profiles
            ],
        )
        profile = profiles[selection]
        if not self.ui.confirm(
            tr("Create project · 4/4 · review"),
            [
                tr("Name       {value0}").format(value0=name),
                tr("Folder     {value0}").format(value0=folder),
                tr("Profile    {value0}").format(value0=profile.name),
                *configuration_lines(profile.latest),
                "",
                tr("Each project has its own planned network, containers and volumes."),
            ],
        ):
            return
        project = self.app.create_project(name, Path(folder), profile.name)
        self.ui.notice(
            tr("Project saved"),
            [
                tr(
                    "{value0} is ready. Use 'brig run {value1}' to start and enter it."
                ).format(value0=project.name, value1=project.name)
            ],
        )

    def projects(self) -> None:
        selected = 0
        while True:
            try:
                projects = self.app.state.projects
                records = list_rows(self.app, "project") + [tr("+ Create project")]
                index = choose_list(
                    self.ui, tr("Projects"), records, min(selected, len(records) - 1)
                )
                selected = index
                if index == len(projects):
                    self.project_wizard()
                else:
                    self.project_detail(projects[index].name)
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice(
                    tr("Could not complete action"), [str(error)], error=True
                )

    def delete_project(self, name: str) -> bool:
        project = self.app.project_for_deletion(name)
        if not self.ui.confirm(
            tr("Delete project '{value0}'").format(value0=project.name),
            [
                tr("Name       {value0}").format(value0=project.name),
                tr("Folder     {value0}").format(value0=project.path or tr("(none)")),
                tr("Profile    {value0}").format(value0=project.profile),
                tr("Only the Brig registration will be deleted."),
                tr("Your local folder, code, and profile will be kept."),
            ],
            action="Delete project",
        ):
            return False
        self.ui.notice(tr("Project deleted"), [self.app.delete_project(project.name)])
        return True

    def project_detail(self, name: str) -> None:
        while True:
            try:
                project = self.app.project(name)
                choice = self.ui.choose(
                    f"{name} · {tr(self.app.project_status(project))}",
                    [
                        tr("View configuration and environment"),
                        tr("Start"),
                        tr("Stop"),
                        tr("Run agent"),
                        tr("Shell"),
                        tr("Apply profile update"),
                        tr("Delete project"),
                        tr("View Dockerfile"),
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
                    agent = choose_agent(project, terminal=self.ui)
                    message = getattr(self.ui, "external", lambda action: action())(
                        lambda agent=agent: self.app.run_agent(name, agent)
                    )
                elif choice == 4:
                    agent = choose_agent(project, terminal=self.ui)
                    message = getattr(self.ui, "external", lambda action: action())(
                        lambda agent=agent: self.app.shell(name, agent=agent)
                    )
                elif choice == 5:
                    latest = self.app.profile(project.profile).latest
                    if not self.ui.confirm(
                        tr("Apply profile update"),
                        [
                            tr("Current version: {value0}").format(
                                value0=project.configuration.number
                            ),
                            *configuration_lines(latest),
                            tr("Stop the project before applying an update."),
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
                        tr("Generated Dockerfile"),
                        self.app.project_dockerfile(name, Path.cwd()).splitlines(),
                    )
                    continue
                if message:
                    self.ui.notice(tr("Result"), message.splitlines())
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice(
                    tr("Could not complete action"), [str(error)], error=True
                )
