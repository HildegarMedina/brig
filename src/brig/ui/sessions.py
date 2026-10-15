"""Host-side login and update prompts shared by CLI and dashboard sessions."""

import getpass
import os
import sys

from brig.agent_updates import newer, releases
from brig.auth_proxy.providers import PROVIDERS
from brig.errors import BrigError, Cancelled, PendingReferences
from brig.i18n import tr


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def confirm(message):
    return input(message + " " + tr("[y/N]: ")).strip().casefold() in (
        "y",
        "yes",
        "s",
        "si",
        "sí",
        "sim",
    )


def with_reference_prompt(app, project, action, *, no_input=False):
    try:
        return action()
    except PendingReferences:
        if no_input or not interactive():
            raise
        try:
            accepted = confirm(
                tr(
                    "References are pending for {project}. Apply them and enter? This closes all existing sessions in the work container."
                ).format(project=project.name)
            )
        except EOFError:
            raise Cancelled from None
        if not accepted:
            raise Cancelled from None
        app.apply_references(project.name)
        return action()


def update_agents(app, project, *, force=False, yes=False, no_input=False):
    if app.engine.simulated:
        return tr("Agent updates are unavailable in simulation mode.")
    try:
        available = releases(
            app.engine.directory, project.configuration.selected_agents, force=force
        )
        installed = app.engine.agent_versions(project)
    except BrigError as error:
        if force:
            raise
        print(str(error), file=sys.stderr)
        return ""
    updates = {
        agent: version
        for agent, version in available.items()
        if newer(version, installed[agent])
    }
    if not updates:
        return tr("Agents are up to date.") if force else ""
    for agent, version in updates.items():
        print(f"{agent}: {installed[agent]} → {version}", file=sys.stderr)
    if not yes and (
        no_input
        or not interactive()
        or not confirm(
            tr(
                "Update agents now? This recreates the project environment; leave other active sessions first."
            )
        )
    ):
        return tr(
            "Updates available. Run brig update with --yes to apply them without prompting."
        )
    return app.update_agents(project.name, updates)


def ensure_login(app, project, agent, *, no_input=False):
    if app.engine.has_credentials(project, agent):
        return
    if no_input or not interactive():
        raise BrigError(
            tr(
                "No credentials for {agent}. Run brig auth login {agent} --project {project} from an interactive terminal."
            ).format(agent=agent, project=project.name)
        )
    method = input(
        tr(
            "No credentials for {agent}. Choose authentication: [1] Sign in [2] API key: "
        ).format(agent=agent)
    ).strip()
    if method in ("", "1"):
        app.authenticate_agent(project.name, agent)
    elif method == "2":
        provider = None
        if agent == "opencode":
            provider = input(
                tr("API provider ({providers}): ").format(
                    providers=", ".join(PROVIDERS)
                )
            ).strip()
            if provider not in PROVIDERS:
                raise BrigError(
                    tr("Unsupported authentication provider: {provider}").format(
                        provider=provider
                    )
                )
        key = getpass.getpass(tr("Provider API key (hidden): "))
        app.authenticate_agent(project.name, agent, provider=provider, key=key)
    else:
        raise BrigError(tr("Choose authentication method 1 or 2."))
    if not app.engine.has_credentials(project, agent):
        raise BrigError(
            tr("Authentication did not save usable credentials. Retry brig auth login.")
        )


def run_agent(app, project, agent, *, no_input=False, check_updates=True):
    def prepare(current):
        if app.engine.simulated:
            return
        if (
            check_updates
            and not os.environ.get("BRIG_NO_UPDATE_CHECK")
            and not no_input
            and interactive()
        ):
            message = update_agents(app, current)
            if message:
                print(message, file=sys.stderr)
        ensure_login(app, current, agent, no_input=no_input)

    return with_reference_prompt(
        app,
        project,
        lambda: app.run_agent(project.name, agent, before_launch=prepare),
        no_input=no_input,
    )
