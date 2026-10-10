"""Versioned JSON persistence with validation and atomic replacement."""

import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from brig.errors import BrigError
from brig.models import Profile, State
from brig.persistence.codec import SCHEMA_VERSION, decode_state
from brig.persistence.profile_yaml import profile_path, render_profile


class StateStore(Protocol):
    def load(self) -> State | None: ...

    def save(self, state: State) -> None: ...

    def delete_profile(self, state: State, profile: Profile) -> None: ...


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
            raise BrigError(f"Cannot read {self.path}: {error}") from error
        except (ValueError, TypeError, KeyError, AttributeError, BrigError) as error:
            raise BrigError(
                f"Invalid data in {self.path}. File was not changed. "
                "Restore a backup or move this file aside to start fresh."
            ) from error

    def save(self, state: State) -> None:
        payload = {"schema_version": SCHEMA_VERSION, **asdict(state)}
        temporary = None
        created_documents = []
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Immutable revision documents are prepared before committing state.
            # Existing documents are never replaced during project operations.
            for profile in state.profiles:
                for revision in profile.revisions:
                    document = profile_path(
                        self.path.parent, profile.name, revision.number
                    )
                    contents = render_profile(profile.name, revision)
                    if document.exists():
                        if document.read_text(encoding="utf-8") != contents:
                            raise OSError(
                                f"Profile revision document was modified: {document}"
                            )
                        continue
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
            raise BrigError(f"Cannot save {self.path}: {error}") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def delete_profile(self, state: State, profile: Profile) -> None:
        directory = profile_path(self.path.parent, profile.name, 1).parent
        temporary = None
        committed = False
        try:
            # Move revision files aside before committing state. A failed save
            # restores the complete directory, including all previous revisions.
            temporary = Path(
                tempfile.mkdtemp(dir=self.path.parent, prefix=".delete-profile-")
            )
            staged = temporary / "revisions"
            moved = False
            if directory.exists():
                os.replace(directory, staged)
                moved = True
            try:
                self.save(state)
                committed = True
            except Exception:
                if moved:
                    try:
                        os.replace(staged, directory)
                    except OSError as error:
                        raise BrigError(
                            f"Deletion failed and revisions could not be restored. Original YAML files are preserved at {staged}: {error}"
                        ) from error
                raise
        except OSError as error:
            raise BrigError(
                f"Cannot delete profile '{profile.name}': {error}"
            ) from error
        finally:
            if temporary is not None and (
                committed or not (temporary / "revisions").exists()
            ):
                shutil.rmtree(temporary, ignore_errors=True)
