"""Profile and project listing summaries for the command-line interface."""

from brig.application import Application
from brig.ui.cards import render_cards
from brig.ui.presentation import configuration_lines


def profile_list(app: Application) -> str:
    profiles = app.state.profiles
    if not profiles:
        return "No profiles. Use 'brig profile create'."
    return render_cards(
        [(profile.name, configuration_lines(profile.latest)) for profile in profiles],
        "\n".join(
            f"{profile.name} · revision {profile.latest.number}" for profile in profiles
        ),
    )


def project_list(app: Application) -> str:
    projects = app.state.projects
    if not projects:
        return "No projects. Use 'brig project init'."
    records = []
    summaries = []
    for project in projects:
        status = app.project_status(project)
        records.append(
            (
                project.name,
                [
                    f"Profile    {project.profile}",
                    f"Status     {status}",
                    f"Folder     {project.path or '(no folder mounted)'}",
                    *configuration_lines(project.configuration),
                ],
            )
        )
        summaries.append(
            f"{project.name} · {project.profile} r{project.configuration.number} · {status}"
        )
    return render_cards(records, "\n".join(summaries))
