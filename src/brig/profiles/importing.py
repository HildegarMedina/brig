"""Merge immutable imported versions and validate all inheritance in one batch."""

from copy import deepcopy
from dataclasses import asdict

from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Profile, State
from brig.persistence.codec import SCHEMA_VERSION, decode_state


def merge_profiles(state: State, documents: list[Profile]) -> tuple[State, int, int]:
    candidate = deepcopy(state)
    profiles = {profile.name.casefold(): profile for profile in candidate.profiles}
    added = unchanged = 0
    for document in sorted(
        documents, key=lambda profile: (profile.name.casefold(), profile.latest.number)
    ):
        key = document.name.casefold()
        if key not in profiles:
            profile = Profile(document.name, [])
            profiles[key] = profile
            candidate.profiles.append(profile)
        profile = profiles[key]
        if profile.name != document.name:
            raise BrigError(
                tr(
                    "Imported profile name '{value0}' conflicts with '{value1}'."
                ).format(value0=document.name, value1=profile.name)
            )
        version = document.latest
        if version.number <= len(profile.versions):
            if profile.versions[version.number - 1] != version:
                raise BrigError(
                    tr(
                        "Profile '{value0}' version {value1} already exists with different configuration."
                    ).format(value0=profile.name, value1=version.number)
                )
            unchanged += 1
            continue
        expected = len(profile.versions) + 1
        if version.number != expected:
            raise BrigError(
                tr(
                    "Missing version {value0} of profile '{value1}'. Include its earlier YAML versions in the import."
                ).format(value0=expected, value1=profile.name)
            )
        profile.versions.append(version)
        added += 1
    try:
        candidate = decode_state(
            {"schema_version": SCHEMA_VERSION, **asdict(candidate)}
        )
    except (ValueError, TypeError, KeyError, BrigError) as error:
        raise BrigError(
            tr("Cannot import profiles: {value0}").format(value0=error)
        ) from error
    return candidate, added, unchanged
