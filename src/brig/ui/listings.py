"""Profile and project listing summaries for the command-line interface."""

from brig.application import Application
from brig.models import Profile, Project
from brig.ui.cards import render_cards


def profile_card(profile: Profile) -> tuple[str, list[str]]:
    return profile.name, [f"Version    {profile.latest.number}"]


def project_card(project: Project, status: str) -> tuple[str, list[str]]:
    return project.name, [
        f"Status     {status}",
        f"Profile    {project.profile} · version {project.configuration.number}",
    ]


def list_records(app: Application, kind: str) -> list[tuple[str, list[str]]]:
    if kind == "profile":
        return [profile_card(profile) for profile in app.state.profiles]
    return [
        project_card(project, app.project_status(project))
        for project in app.state.projects
    ]


def profile_list(app: Application) -> str:
    profiles = app.state.profiles
    if not profiles:
        return "No profiles. Use 'brig profile create'."
    return render_cards(
        list_records(app, "profile"),
        "\n".join(
            f"{profile.name} · version {profile.latest.number}" for profile in profiles
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
        records.append(project_card(project, status))
        summaries.append(
            f"{project.name} · {project.profile} version {project.configuration.number} · {status}"
        )
    return render_cards(records, "\n".join(summaries))
