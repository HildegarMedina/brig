"""Plain text summaries shared by both user interfaces."""

from brig.application import Application
from brig.i18n import tr
from brig.models import ProfileVersion, Project


def configuration_lines(configuration: ProfileVersion) -> list[str]:
    lines = [tr("Version    {value0}").format(value0=configuration.number)]
    if configuration.extends:
        lines.append(
            tr("Inherits   {value0} · version {value1}").format(
                value0=configuration.extends.profile,
                value1=configuration.extends.version,
            )
        )
    for label, selections in (
        (tr("Runtimes"), configuration.runtimes),
        (tr("Tools"), configuration.tools),
        (tr("Services"), configuration.services),
    ):
        values = ", ".join(f"{name} {version}" for name, version in selections.items())
        lines.append(f"{label:<10} {values or tr('none')}")
    lines.append(
        tr("Agents     {value0}").format(
            value0=", ".join(configuration.selected_agents)
        )
    )
    lines.append(tr("Default    {value0}").format(value0=configuration.agent))
    return lines


def project_lines(
    app: Application, project: Project, *, status: str | None = None
) -> list[str]:
    environment = app.engine.describe(project)
    latest = app.profile(project.profile).latest.number
    update = tr(" · update available") if latest != project.configuration.number else ""
    return [
        tr("Project    {value0}").format(value0=project.name),
        tr("Folder     {value0}").format(
            value0=project.path or tr("(sample project; no folder mounted)")
        ),
        tr("Profile    {value0}{value1}").format(value0=project.profile, value1=update),
        tr("Status     {value0}").format(
            value0=tr(app.project_status(project) if status is None else status)
        ),
        *configuration_lines(project.configuration),
        "",
        tr("Planned environment — not created")
        if app.engine.simulated
        else tr("Docker environment"),
        tr("Dev        {value0}").format(value0=environment.development),
        *[
            tr("Agent      {agent}: {container}").format(
                agent=agent, container=container
            )
            for agent, container in environment.agents.items()
        ],
        tr("Network    {value0}").format(value0=environment.network),
        *[
            tr("Service    {value0}: {value1}").format(value0=name, value1=container)
            for name, container in environment.services.items()
        ],
        *[
            tr("Volume     {value0}").format(value0=volume)
            for volume in environment.volumes
        ],
        tr("Mount      project folder → /workspace; no other host folders"),
    ]
