"""Shared translations, independent of interface and persistence modules."""

import json
import os
from contextvars import ContextVar
from functools import cache
from importlib.resources import files

LANGUAGES = {"en": "English", "es": "Español", "pt": "Português"}
_language = ContextVar("brig_language", default="en")


def normalize_language(value: str) -> str | None:
    code = value.strip().lower().replace("-", "_").split(".")[0].split("_")[0]
    return code if code in LANGUAGES else None


def resolve_language(explicit: str | None = None, saved: str | None = None) -> str:
    for value in (explicit, os.environ.get("BRIG_LANG"), saved):
        if value and (code := normalize_language(value)):
            return code
    # POSIX precedence: an unsupported LC_ALL still overrides LANG.
    locale = next(
        (
            os.environ[key]
            for key in ("LC_ALL", "LC_MESSAGES", "LANG")
            if os.environ.get(key)
        ),
        "en",
    )
    return normalize_language(locale) or "en"


def current_language() -> str:
    return _language.get()


def set_language(code: str):
    if code not in LANGUAGES:
        raise ValueError(tr("Unsupported language: {code}").format(code=code))
    return _language.set(code)


def reset_language(token) -> None:
    _language.reset(token)


@cache
def catalog(code: str) -> dict[str, str]:
    if code == "en":
        return {}
    return json.loads(
        files(__package__)
        .joinpath("catalogs", f"{code}.json")
        .read_text(encoding="utf-8")
    )


def tr(message: str) -> str:
    """Translate a template before formatting; unknown messages remain English."""
    return catalog(current_language()).get(message, message)
