"""Language preferences are separate from immutable environment definitions."""

import json
import os
import tempfile
from pathlib import Path

from brig.errors import BrigError
from brig.i18n import LANGUAGES, tr


def load_language(directory: Path) -> str | None:
    path = directory / "preferences.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or set(raw) != {"language"}
            or raw["language"] not in (*LANGUAGES, "auto")
        ):
            raise ValueError(tr("Invalid language preferences"))
        return None if raw["language"] == "auto" else raw["language"]
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as error:
        raise BrigError(
            tr("Cannot read language preferences at {path}: {error}").format(
                path=path, error=error
            )
        ) from error


def save_language(directory: Path, code: str) -> None:
    if code not in (*LANGUAGES, "auto"):
        raise BrigError(tr("Unsupported language: {code}").format(code=code))
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".preferences-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps({"language": code}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "preferences.json")
    except OSError as error:
        raise BrigError(
            tr("Cannot save language preferences: {error}").format(error=error)
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
