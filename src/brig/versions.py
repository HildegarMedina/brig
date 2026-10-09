"""On-demand release discovery, cached only for one profile operation."""

import json
import re
from collections.abc import Callable, Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

from brig.catalog import COMPONENTS, Component
from brig.errors import BrigError

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def fetch_text(url: str) -> str:
    accept = (
        "application/vnd.npm.install-v1+json"
        if url.startswith("https://registry.npmjs.org/")
        else "application/json, text/plain"
    )
    request = Request(url, headers={"User-Agent": "brig/0.1", "Accept": accept})
    with urlopen(request, timeout=10) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("Version response is too large")
    return data.decode("utf-8")


def docker_versions(text: str) -> Iterable[str]:
    # Only Linux blocks; moving aliases and image variants are filtered later.
    for block in text.split("\n\n"):
        architectures = next(
            (line for line in block.splitlines() if line.startswith("Architectures:")),
            "",
        )
        if not architectures or all(
            a.strip().startswith("windows-")
            for a in architectures.split(":", 1)[1].split(",")
        ):
            continue
        for line in block.splitlines():
            if line.startswith(("Tags:", "SharedTags:")):
                yield from (tag.strip() for tag in line.split(":", 1)[1].split(","))


def pypi_versions(text: str) -> Iterable[str]:
    data = json.loads(text)
    for version, files in data["releases"].items():
        if any(not file.get("yanked", False) for file in files):
            yield version


def npm_versions(text: str) -> Iterable[str]:
    data = json.loads(text)
    for version, metadata in data["versions"].items():
        if metadata.get("dist", {}).get("tarball") and not metadata.get("deprecated"):
            yield version


# New source types need only a URL builder and a parser.
PROVIDERS = {
    "docker": (
        lambda package: (
            f"https://raw.githubusercontent.com/docker-library/official-images/master/library/{package}"
        ),
        docker_versions,
    ),
    "pypi": (lambda package: f"https://pypi.org/pypi/{package}/json", pypi_versions),
    "npm": (lambda package: f"https://registry.npmjs.org/{package}", npm_versions),
}


def source_label(component: Component) -> str:
    return {"docker": "Docker Official Images", "pypi": "PyPI", "npm": "npm registry"}[
        component.provider
    ]


class LiveVersionCatalog:
    def __init__(self, fetch: Callable[[str], str] = fetch_text):
        self.fetch = fetch
        self._snapshot: dict[str, tuple[str, ...]] = {}

    def versions(self, name: str) -> tuple[str, ...]:
        if name in self._snapshot:
            return self._snapshot[name]
        component = COMPONENTS[name]
        url_for, parse = PROVIDERS[component.provider]
        try:
            found = {
                value
                for value in parse(self.fetch(url_for(component.package)))
                if re.fullmatch(
                    rf"[0-9]+(?:\.[0-9]+){{{component.version_parts - 1}}}", value
                )
                and value.startswith(component.version_prefix)
            }
            result = tuple(
                sorted(
                    found,
                    key=lambda value: tuple(map(int, value.split("."))),
                    reverse=True,
                )
            )
            if not result:
                raise ValueError("No stable, exact versions were returned")
        except (
            OSError,
            URLError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as error:
            raise BrigError(
                f"Cannot fetch versions for {component.label} from {source_label(component)}: {error}. "
                "Check your connection and retry. No fallback versions were selected."
            ) from error
        self._snapshot[name] = result
        return result
