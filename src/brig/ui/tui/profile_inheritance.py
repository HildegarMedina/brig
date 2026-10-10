"""Base-profile selection shared by profile creation and version editing."""

from dataclasses import replace

from brig.application import Application
from brig.errors import BrigError
from brig.models import ProfileParent, ProfileVersion
from brig.profile_inheritance import resolve_base
from brig.ui.tui.terminal import Terminal


def local_defaults(
    app: Application, existing: ProfileVersion | None
) -> ProfileVersion | None:
    if existing is None or existing.extends is None:
        return existing
    base = resolve_base(app.state.profiles, existing.extends)
    selections = {
        section: {
            name: value
            for name, value in getattr(existing, section).items()
            if name not in getattr(base, section)
        }
        for section in ("runtimes", "tools", "services")
    }
    return replace(
        existing,
        **selections,
        agents=[
            agent
            for agent in existing.selected_agents
            if agent not in base.selected_agents
        ],
    )


def choose_parent(
    app: Application,
    ui: Terminal,
    existing: ProfileVersion | None,
    *,
    base: str | None = None,
    base_version: int | None = None,
    update_base: bool = False,
) -> ProfileParent | None:
    if existing is not None:
        parent = existing.extends
        if parent is None:
            if update_base:
                raise BrigError("This profile does not inherit a base profile.")
            return None
        latest = app.profile(parent.profile).latest.number
        if latest != parent.version and not update_base:
            update_base = (
                ui.choose(
                    "Inherited base version",
                    [
                        f"Keep {parent.profile} v{parent.version}",
                        f"Update to v{latest}",
                    ],
                    default=0,
                )
                == 1
            )
        return ProfileParent(parent.profile, latest) if update_base else parent
    if base_version is not None and base is None:
        raise BrigError("--base-version requires --base.")
    if base is None:
        profiles = app.state.profiles
        if not profiles:
            return None
        index = ui.choose(
            "Base profile",
            ["Create independently", *[profile.name for profile in profiles]],
            default=0,
        )
        if index == 0:
            return None
        base = profiles[index - 1].name
    profile = app.profile(base)
    if base_version is None:
        versions = list(reversed(profile.versions))
        index = ui.choose(
            f"Inherit {profile.name} version",
            [f"Version {version.number}" for version in versions],
            default=0,
        )
        base_version = versions[index].number
    parent = ProfileParent(profile.name, base_version)
    resolve_base(app.state.profiles, parent)
    return parent
