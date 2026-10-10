"""Merge immutable imported versions and validate all inheritance in one batch."""

from copy import deepcopy
from dataclasses import asdict

from brig.errors import BrigError
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
                f"Imported profile name '{document.name}' conflicts with '{profile.name}'."
            )
        version = document.latest
        if version.number <= len(profile.versions):
            if profile.versions[version.number - 1] != version:
                raise BrigError(
                    f"Profile '{profile.name}' version {version.number} already exists with different configuration."
                )
            unchanged += 1
            continue
        expected = len(profile.versions) + 1
        if version.number != expected:
            raise BrigError(
                f"Missing version {expected} of profile '{profile.name}'. Include its earlier YAML versions in the import."
            )
        profile.versions.append(version)
        added += 1
    try:
        candidate = decode_state(
            {"schema_version": SCHEMA_VERSION, **asdict(candidate)}
        )
    except (ValueError, TypeError, KeyError, BrigError) as error:
        raise BrigError(f"Cannot import profiles: {error}") from error
    return candidate, added, unchanged
