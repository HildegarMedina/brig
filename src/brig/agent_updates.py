"""Stable agent release discovery with a bounded, daily host-side cache."""

import json
import re
import time
from pathlib import Path

from brig.components.providers import fetch_text
from brig.docker.workspace import DockerWorkspace
from brig.errors import BrigError
from brig.i18n import tr

SOURCES = {
    "claude": "https://registry.npmjs.org/@anthropic-ai%2fclaude-code/stable",
    "codex": "https://registry.npmjs.org/@openai%2fcodex/latest",
    "opencode": "https://api.github.com/repos/anomalyco/opencode/releases/latest",
}
VERSION = re.compile(r"\d+\.\d+\.\d+")


def version_number(text):
    match = re.search(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", text)
    if not match:
        raise ValueError("Invalid agent version")
    return match.group()


def releases(directory: Path, agents, *, force=False, fetch=fetch_text, now=None):
    now = time.time() if now is None else now
    path = directory / "agent-release-cache.json"
    try:
        cache = json.loads(path.read_text())
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    result = {}
    try:
        for agent in agents:
            entry = cache.get(agent, {})
            if (
                not force
                and isinstance(entry, dict)
                and isinstance(entry.get("checked"), (int, float))
                and 0 <= now - entry["checked"] < 86400
                and isinstance(entry.get("version"), str)
                and VERSION.fullmatch(entry["version"])
            ):
                result[agent] = entry["version"]
                continue
            data = json.loads(fetch(SOURCES[agent]))
            value = data["tag_name"] if agent == "opencode" else data["version"]
            version = version_number(value)
            result[agent] = version
            cache[agent] = {"checked": now, "version": version}
        DockerWorkspace.write(path, json.dumps(cache))
    except (OSError, ValueError, KeyError, TypeError, BrigError) as error:
        raise BrigError(
            tr("Cannot check agent updates. Check your connection and retry.")
        ) from error
    return result


def newer(available, installed):
    return tuple(map(int, available.split("."))) > tuple(map(int, installed.split(".")))
