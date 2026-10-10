"""Pinned profile relationships and validation, without environment execution."""

from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Profile, ProfileParent, ProfileVersion


def resolve_base(profiles: list[Profile], parent: ProfileParent) -> ProfileVersion:
    if not isinstance(parent.profile, str) or type(parent.version) is not int:
        raise BrigError(tr("Invalid base profile reference."))
    for profile in profiles:
        if profile.name == parent.profile:
            for version in profile.versions:
                if version.number == parent.version:
                    return version
    raise BrigError(
        tr("Unknown base profile version: {value0} v{value1}.").format(
            value0=parent.profile, value1=parent.version
        )
    )


def would_cycle(profiles: list[Profile], child: str, parent: str) -> bool:
    by_name = {profile.name: profile for profile in profiles}
    pending = [parent]
    visited = set()
    while pending:
        name = pending.pop()
        if name == child:
            return True
        if name in visited:
            continue
        visited.add(name)
        profile = by_name.get(name)
        if profile:
            pending.extend(
                version.extends.profile
                for version in profile.versions
                if version.extends
            )
    return False


def validate_inherited(configuration: ProfileVersion, base: ProfileVersion) -> None:
    for section in ("runtimes", "tools", "services"):
        selections = getattr(configuration, section)
        for name, version in getattr(base, section).items():
            if selections.get(name) != version:
                raise BrigError(
                    tr(
                        "Inherited {value0} {value1} cannot be removed or overridden."
                    ).format(value0=name, value1=version)
                )
    if not set(base.selected_agents).issubset(configuration.selected_agents):
        raise BrigError(tr("Inherited agents cannot be removed."))


def validate_relationships(profiles: list[Profile]) -> None:
    for profile in profiles:
        for version in profile.versions:
            if version.extends:
                base = resolve_base(profiles, version.extends)
                if would_cycle(profiles, profile.name, version.extends.profile):
                    raise BrigError(tr("Profile inheritance cannot contain cycles."))
                validate_inherited(version, base)
