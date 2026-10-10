"""Plain text summaries shared by both user interfaces."""

from brig.application import Application
from brig.models import ProfileRevision, Project


def configuration_lines(configuration: ProfileRevision) -> list[str]:
    lines = [f"Version    {configuration.number}"]
    for label, selections in (
        ("Runtimes", configuration.runtimes),
        ("Tools", configuration.tools),
        ("Services", configuration.services),
    ):
        values = ", ".join(f"{name} {version}" for name, version in selections.items())
        lines.append(f"{label:<10} {values or 'none'}")
    lines.append(f"Agents     {', '.join(configuration.selected_agents)}")
    lines.append(f"Default    {configuration.agent}")
    return lines


def project_lines(app: Application, project: Project) -> list[str]:
    environment = app.engine.describe(project)
    latest = app.profile(project.profile).latest.number
    update = " · update available" if latest != project.configuration.number else ""
    return [
        f"Project    {project.name}",
        f"Folder     {project.path or '(sample project; no folder mounted)'}",
        f"Profile    {project.profile}{update}",
        f"Status     {app.project_status(project)}",
        *configuration_lines(project.configuration),
        "",
        "Planned environment — not created"
        if app.engine.simulated
        else "Docker environment",
        f"Dev        {environment.development}",
        f"Network    {environment.network}",
        *[
            f"Service    {name}: {container}"
            for name, container in environment.services.items()
        ],
        *[f"Volume     {volume}" for volume in environment.volumes],
        "Mount      project folder → /workspace; no other host folders",
    ]
