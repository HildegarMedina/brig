"""HTTP transport and release parsers for supported upstream providers."""

import json
import platform
import re
from collections.abc import Callable, Iterable
from urllib.request import Request, urlopen

from brig.components.catalog import COMPONENTS, Component
from brig.components.compatibility import ReleaseInfo
from brig.i18n import tr

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
        raise ValueError(tr("Version response is too large"))
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


def dockerhub_versions(text: str) -> Iterable[str]:
    # Release candidates and moving aliases are filtered later.
    for entry in json.loads(text)["results"]:
        yield entry["name"]


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
    # Newest 100 tags; older releases are not maintained upstream.
    "dockerhub": (
        lambda package: (
            f"https://hub.docker.com/v2/repositories/{package}/tags"
            "?page_size=100&ordering=last_updated"
        ),
        dockerhub_versions,
    ),
    "pypi": (lambda package: f"https://pypi.org/pypi/{package}/json", pypi_versions),
    "npm": (lambda package: f"https://registry.npmjs.org/{package}", npm_versions),
    "composer": (lambda package: "https://getcomposer.org/versions", composer_versions),
}


# Docker Hub architecture names for this machine; others accept any Linux image.
HOST_ARCHITECTURE = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}.get(platform.machine().lower())


def image_tag_url(image: str) -> str:
    repository, tag = image.rsplit(":", 1)
    namespace, _, name = repository.rpartition("/")
    return (
        f"https://hub.docker.com/v2/namespaces/{namespace or 'library'}"
        f"/repositories/{name}/tags/{tag}"
    )


def image_published(text: str, architecture: str | None = HOST_ARCHITECTURE) -> bool:
    # Official manifests list releases hours before their images are pushed.
    return any(
        image.get("os") == "linux"
        and image.get("status", "active") == "active"
        and architecture in (None, image.get("architecture"))
        for image in json.loads(text).get("images") or ()
    )


# Tag that exists only when a Java tool release is published for a JDK major.
JAVA_TOOL_TAGS = {
    "maven": "{version}-eclipse-temurin-{java}",
    "gradle": "{version}-jdk{java}",
}
JDK_MAJOR = re.compile(r"(?:eclipse-temurin-|jdk)([0-9]+)\b")


def source_label(component: Component) -> str:
    return {
        "docker": "Docker Official Images",
        "dockerhub": "Docker Hub",
        "pypi": "PyPI",
        "npm": tr("npm registry"),
        "composer": tr("Composer releases"),
    }[component.provider]


def release_info(
    name: str, text: str, versions: tuple[str, ...], fetch: Callable[[str], str]
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
    elif name in JAVA_TOOL_TAGS:
        # Upstream publishes each release only for the JDKs it supports.
        tags = set(docker_versions(text))
        candidates = set(JDK_MAJOR.findall(" ".join(tags)))
        for version in versions:
            majors = sorted(
                (
                    major
                    for major in candidates
                    if JAVA_TOOL_TAGS[name].format(version=version, java=major) in tags
                ),
                key=int,
            )
            info[version] = ReleaseInfo(
                requirements=tuple(majors) or None, dialect="exact"
            )
    elif name == "java":
        lts = json.loads(fetch("https://api.adoptium.net/v3/info/available_releases"))[
            "available_lts_releases"
        ]
        info = {
            version: ReleaseInfo("LTS" if int(version) in lts else "Stable")
            for version in versions
        }
    elif name == "node":
        metadata = {
            entry["version"].removeprefix("v"): entry
            for entry in json.loads(fetch("https://nodejs.org/dist/index.json"))
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
            fetch(
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
