"""Compact profile and project summaries shared by both user interfaces."""

from brig.application import Application
from brig.i18n import tr


def list_rows(app: Application, kind: str) -> list[str]:
    if kind == "profile":
        return [
            tr("{value0} · version {value1}").format(
                value0=profile.name, value1=profile.latest.number
            )
            for profile in app.state.profiles
        ]
    return [
        tr("{value0} · {value1} · {value2} version {value3}").format(
            value0=project.name,
            value1=tr(app.project_status(project)),
            value2=project.profile,
            value3=project.configuration.number,
        )
        for project in app.state.projects
    ]


def profile_list(app: Application) -> str:
    return "\n".join(list_rows(app, "profile")) or tr(
        "No profiles. Use 'brig profile create'."
    )


def project_list(app: Application) -> str:
    return "\n".join(list_rows(app, "project")) or tr(
        "No projects. Use 'brig project init'."
    )
