"""Versioned JSON persistence with validation and atomic replacement."""

import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Profile, State
from brig.persistence.codec import SCHEMA_VERSION, decode_state
from brig.persistence.profile_yaml import legacy_profile, profile_path, render_profile


class StateStore(Protocol):
    def load(self) -> State | None: ...

    def save(self, state: State) -> None: ...

    def delete_profile(self, state: State, profile: Profile) -> None: ...

    def replace_profiles(self, state: State, names: list[str]) -> None: ...


def default_data_directory() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "brig"


class JsonStateStore:
    def __init__(self, directory: Path):
        self.path = directory / "state.json"

    def load(self) -> State | None:
        try:
            contents = self.path.read_text(encoding="utf-8")
            return decode_state(json.loads(contents))
        except FileNotFoundError:
            return None
        except OSError as error:
            raise BrigError(
                tr("Cannot read {value0}: {value1}").format(
                    value0=self.path, value1=error
                )
            ) from error
        except (ValueError, TypeError, KeyError, AttributeError, BrigError) as error:
            raise BrigError(
                tr(
                    "Invalid data in {value0}. File was not changed. Restore a backup or move this file aside to start fresh."
                ).format(value0=self.path)
            ) from error

    def save(self, state: State) -> None:
        payload = {"schema_version": SCHEMA_VERSION, **asdict(state)}
        temporary = None
        created_documents = []
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Immutable version documents are prepared before committing state.
            # Existing documents are never replaced during project operations.
            for profile in state.profiles:
                for version in profile.versions:
                    document = profile_path(
                        self.path.parent, profile.name, version.number
                    )
                    contents = render_profile(profile.name, version)
                    if document.exists():
                        if document.read_text(encoding="utf-8") != contents:
                            raise OSError(
                                tr(
                                    "Profile version document was modified: {value0}"
                                ).format(value0=document)
                            )
                        continue
                    legacy, expected = legacy_profile(
                        self.path.parent, profile.name, version
                    )
                    if (
                        legacy.exists()
                        and legacy.read_text(encoding="utf-8") != expected
                    ):
                        raise OSError(
                            tr("Legacy profile document was modified: {value0}").format(
                                value0=legacy
                            )
                        )
                    document.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=document.parent,
                        prefix=".profile-",
                        suffix=".tmp",
                        delete=False,
                    ) as stream:
                        temporary = Path(stream.name)
                        stream.write(contents)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, document)
                    created_documents.append(document)
                    temporary = None
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".state-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            for document in created_documents:
                document.unlink(missing_ok=True)
            raise BrigError(
                tr("Cannot save {value0}: {value1}").format(
                    value0=self.path, value1=error
                )
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def delete_profile(self, state: State, profile: Profile) -> None:
        try:
            self.replace_profiles(state, [profile.name])
        except OSError as error:
            raise BrigError(
                tr("Cannot delete profile '{value0}': {value1}").format(
                    value0=profile.name, value1=error
                )
            ) from error

    def replace_profiles(self, state: State, names: list[str]) -> None:
        """Rewrite the version documents of the named profiles from state.

        Version files are moved aside before committing state; a failed save
        restores every directory, including all previous versions.
        """
        directories = [
            profile_path(self.path.parent, name, 1).parent.parent for name in names
        ]
        temporary = Path(
            tempfile.mkdtemp(dir=self.path.parent, prefix=".replace-profiles-")
        )
        moved = []
        committed = False
        try:
            for index, directory in enumerate(directories):
                if directory.exists():
                    staged = temporary / str(index)
                    os.replace(directory, staged)
                    moved.append((staged, directory))
            self.save(state)
            committed = True
        finally:
            if not committed:
                for staged, directory in moved:
                    try:
                        # Remove documents a failed save may have created.
                        shutil.rmtree(directory, ignore_errors=True)
                        os.replace(staged, directory)
                    except OSError as error:
                        raise BrigError(
                            tr(
                                "Profile changes failed and versions could not be restored. Original YAML files are preserved at {value0}: {value1}"
                            ).format(value0=staged, value1=error)
                        ) from error
            shutil.rmtree(temporary, ignore_errors=True)
