"""Compact profile and project summaries shared by both user interfaces."""

from brig.application import Application


def list_rows(app: Application, kind: str) -> list[str]:
    if kind == "profile":
        return [
            f"{profile.name} · version {profile.latest.number}"
            for profile in app.state.profiles
        ]
    return [
        f"{project.name} · {app.project_status(project)} · "
        f"{project.profile} version {project.configuration.number}"
        for project in app.state.projects
    ]


def profile_list(app: Application) -> str:
    return (
        "\n".join(list_rows(app, "profile"))
        or "No profiles. Use 'brig profile create'."
    )


def project_list(app: Application) -> str:
    return (
        "\n".join(list_rows(app, "project")) or "No projects. Use 'brig project init'."
    )
