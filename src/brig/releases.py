"""Stable Brig release discovery and checksum-verified package downloads."""

import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

from packaging.version import Version

from brig import __version__
from brig.errors import BrigError
from brig.i18n import tr

REPOSITORY = "HildegarMedina/brig"
RELEASES = f"https://github.com/{REPOSITORY}/releases/download"
LATEST = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
REQUIREMENTS = "brig-requirements.txt"


def stable_version(value):
    if not isinstance(value, str) or not VERSION_PATTERN.fullmatch(
        value.removeprefix("v")
    ):
        raise BrigError(tr("Use a stable Brig version such as 1.0.0."))
    return value.removeprefix("v")


def fetch(url, *, limit=16 * 1024 * 1024):
    request = Request(
        url,
        headers={
            "User-Agent": f"brig/{__version__}",
            "Accept": "application/json, application/octet-stream",
        },
    )
    with urlopen(request, timeout=5) as response:
        if not response.url.startswith("https://"):
            raise ValueError("Release download redirected outside HTTPS")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release response is too large")
    return data


def latest_version(*, download=fetch):
    try:
        release = json.loads(download(LATEST, limit=256 * 1024))
        if release.get("draft") or release.get("prerelease"):
            raise ValueError("Not a stable release")
        return stable_version(release["tag_name"])
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        BrigError,
    ) as error:
        raise BrigError(
            tr("Cannot check Brig updates. Check your connection and retry.")
        ) from error


def newer(available, installed=__version__):
    return Version(available) > Version(installed)


def release_files(version, directory: Path, *, download=fetch):
    version = stable_version(version)
    wheel = f"brig-{version}-py3-none-any.whl"
    url = f"{RELEASES}/v{version}"
    try:
        manifest = download(f"{url}/SHA256SUMS", limit=16384).decode("ascii")
        hashes = {}
        for line in manifest.splitlines():
            digest, name = line.split()
            if (
                not re.fullmatch(r"[0-9a-f]{64}", digest)
                or name in hashes
                or "/" in name
                or "\\" in name
            ):
                raise ValueError("Invalid checksum manifest")
            hashes[name] = digest
        paths = []
        for name in (wheel, REQUIREMENTS):
            expected = hashes[name]
            data = download(f"{url}/{name}")
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Checksum mismatch")
            path = directory / name
            path.write_bytes(data)
            paths.append(path)
        return paths
    except (OSError, ValueError, KeyError, UnicodeError) as error:
        raise BrigError(
            tr(
                "Cannot download or verify Brig {version}. Installation was not started."
            ).format(version=version)
        ) from error
