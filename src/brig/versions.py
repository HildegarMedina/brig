"""On-demand release discovery, cached only for one profile operation."""

import json
import re
from collections.abc import Callable, Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

from brig.catalog import COMPONENTS, Component
from brig.errors import BrigError
from brig.compatibility import ReleaseInfo

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


def composer_versions(text: str) -> Iterable[str]:
    for entry in json.loads(text)["stable"]:
        if not entry.get("eol"):
            yield entry["version"]


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
    "composer": (lambda package: "https://getcomposer.org/versions", composer_versions),
}


def source_label(component: Component) -> str:
    return {
        "docker": "Docker Official Images",
        "pypi": "PyPI",
        "npm": "npm registry",
        "composer": "Composer releases",
    }[component.provider]


class LiveVersionCatalog:
    def __init__(self, fetch: Callable[[str], str] = fetch_text):
        self.fetch = fetch
        self._snapshot: dict[str, tuple[str, ...]] = {}
        self._info: dict[str, dict[str, ReleaseInfo]] = {}

    def versions(self, name: str) -> tuple[str, ...]:
        if name in self._snapshot:
            return self._snapshot[name]
        component = COMPONENTS[name]
        url_for, parse = PROVIDERS[component.provider]
        try:
            text = self.fetch(url_for(component.package))
            found = {
                value
                for value in parse(text)
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
            info = self._release_info(name, text, result)
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
        self._info[name] = info
        return result

    def _release_info(
        self, name: str, text: str, versions: tuple[str, ...]
    ) -> dict[str, ReleaseInfo]:
        component = COMPONENTS[name]
        info = {version: ReleaseInfo() for version in versions}
        if component.provider == "pypi":
            files = json.loads(text)["releases"]
            for version in versions:
                requirements = tuple(
                    sorted(
                        {
                            file["requires_python"]
                            for file in files[version]
                            if not file.get("yanked")
                            and isinstance(file.get("requires_python"), str)
                            and file["requires_python"].strip()
                        }
                    )
                )
                info[version] = ReleaseInfo(
                    requirements=requirements or None, dialect="python"
                )
        elif component.provider == "npm":
            metadata = json.loads(text)["versions"]
            for version in versions:
                requirement = metadata[version].get("engines", {}).get("node")
                info[version] = ReleaseInfo(
                    requirements=(requirement,)
                    if isinstance(requirement, str) and requirement.strip()
                    else None,
                    dialect="npm",
                )
        elif component.provider == "composer":
            metadata = {entry["version"]: entry for entry in json.loads(text)["stable"]}
            for version in versions:
                entry = metadata[version]
                minimum = entry.get("min-php")
                requirement = (
                    f"{minimum // 10000}.{minimum // 100 % 100}.{minimum % 100}"
                    if type(minimum) is int and minimum > 0
                    else None
                )
                info[version] = ReleaseInfo(
                    "LTS" if entry.get("lts") is True else "Stable",
                    (requirement,) if requirement else None,
                    "minimum",
                )
        elif name == "node":
            metadata = {
                entry["version"].removeprefix("v"): entry
                for entry in json.loads(
                    self.fetch("https://nodejs.org/dist/index.json")
                )
            }
            for version in versions:
                entry = metadata.get(version)
                info[version] = ReleaseInfo(
                    "LTS"
                    if entry and entry.get("lts")
                    else "Current"
                    if entry
                    else "Channel unverified"
                )
        elif name == "mysql":
            # The official image repository keeps Innovation under its named key,
            # and maintained LTS series under numbered keys (including older LTS).
            metadata = json.loads(
                self.fetch(
                    "https://raw.githubusercontent.com/docker-library/mysql/master/versions.json"
                )
            )
            channels = {
                entry["version"]: "Innovation"
                if branch == "innovation"
                else "LTS"
                if re.fullmatch(r"[0-9]+\.[0-9]+", branch)
                else "Channel unverified"
                for branch, entry in metadata.items()
            }
            info = {
                version: ReleaseInfo(channels.get(version, "Channel unverified"))
                for version in versions
            }
        return info

    def label(self, name: str, version: str) -> str:
        self.versions(name)
        return f"{version} · {self._info[name][version].channel}"

    def preferred_version(self, name: str, versions: list[str]) -> str:
        self.versions(name)
        if name in ("node", "mysql"):
            return next(
                (
                    version
                    for version in versions
                    if self._info[name][version].channel == "LTS"
                ),
                versions[0],
            )
        return versions[0]

    def compatibility_issue(
        self, name: str, version: str, runtimes: dict[str, str]
    ) -> str | None:
        component = COMPONENTS[name]
        if component.runtime is None:
            return None
        self.versions(name)
        runtime = runtimes.get(component.runtime)
        info = self._info[name].get(version)
        if runtime and info and info.supports(runtime):
            return None
        requirement = (
            info.requirement_label() if info else "release metadata is unavailable"
        )
        return f"{component.label} {version} cannot be verified for {COMPONENTS[component.runtime].label} {runtime or '(not selected)'}. Requires: {requirement}. Choose a compatible tool or change the runtime."

    def compatible_versions(
        self, name: str, runtimes: dict[str, str]
    ) -> tuple[str, ...]:
        return tuple(
            version
            for version in self.versions(name)
            if self.compatibility_issue(name, version, runtimes) is None
        )
