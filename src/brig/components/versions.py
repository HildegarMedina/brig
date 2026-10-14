"""On-demand release discovery, cached only for one profile operation."""

import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError

from brig.components.catalog import COMPONENTS
from brig.components.compatibility import ReleaseInfo
from brig.components.providers import (
    PROVIDERS,
    fetch_text,
    image_published,
    image_tag_url,
    release_info,
    source_label,
)
from brig.errors import BrigError
from brig.i18n import tr


class LiveVersionCatalog:
    def __init__(self, fetch: Callable[[str], str] = fetch_text):
        self.fetch = fetch
        self._snapshot: dict[str, tuple[str, ...]] = {}
        self._info: dict[str, dict[str, ReleaseInfo]] = {}
        self._published: dict[str, bool] = {}

    def _check_published(self, images: Iterable[str]) -> None:
        def check(image: str) -> bool:
            try:
                return image_published(self.fetch(image_tag_url(image)))
            except HTTPError as error:
                if error.code == 404:
                    return False
                failure = error
            except (OSError, ValueError, TypeError, AttributeError) as error:
                failure = error
            raise BrigError(
                tr(
                    "Cannot verify the {value0} image on Docker Hub: {value1}. Check your connection and retry."
                ).format(value0=image, value1=failure)
            ) from failure

        pending = sorted(set(images) - self._published.keys())
        with ThreadPoolExecutor(max_workers=8) as pool:
            self._published.update(zip(pending, pool.map(check, pending), strict=True))

    def published(self, image: str) -> bool:
        self._check_published((image,))
        return self._published[image]

    def versions(self, name: str) -> tuple[str, ...]:
        if name in self._snapshot:
            return self._snapshot[name]
        component = COMPONENTS[name]
        url_for, parse = PROVIDERS[component.provider]
        try:
            text = self.fetch(url_for(component.package))
            tags = set(parse(text))
            found = {
                value
                for value in tags
                if re.fullmatch(
                    rf"[0-9]+(?:\.[0-9]+){{{component.version_parts - 1}}}", value
                )
                and value.startswith(component.version_prefix)
                and (not component.tag_suffix or value + component.tag_suffix in tags)
            }
            if component.image and "{java}" not in component.image:
                images = {
                    value: component.image.format(version=value) for value in found
                }
                self._check_published(images.values())
                found = {value for value in found if self._published[images[value]]}
            result = tuple(
                sorted(
                    found,
                    key=lambda value: tuple(map(int, value.split("."))),
                    reverse=True,
                )
            )
            if not result:
                raise ValueError(
                    tr("No stable, exact versions with published images were returned")
                )
            info = release_info(name, text, result, self.fetch)
        except (
            OSError,
            URLError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as error:
            raise BrigError(
                tr(
                    "Cannot fetch versions for {value0} from {value1}: {value2}. Check your connection and retry. No fallback versions were selected."
                ).format(
                    value0=component.label, value1=source_label(component), value2=error
                )
            ) from error
        self._snapshot[name] = result
        self._info[name] = info
        return result

    def label(self, name: str, version: str) -> str:
        self.versions(name)
        return f"{version} · {tr(self._info[name][version].channel)}"

    def preferred_version(self, name: str, versions: list[str]) -> str:
        self.versions(name)
        if name in ("node", "mysql", "java"):
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
            if "{java}" not in component.image:
                return None
            image = component.image.format(version=version, java=runtime)
            if self.published(image):
                return None
            return tr(
                "{value0} {value1} is not yet published for {value2} {value3} on Docker Hub ({value4}). Choose another version or retry later."
            ).format(
                value0=component.label,
                value1=version,
                value2=COMPONENTS[component.runtime].label,
                value3=runtime,
                value4=image,
            )
        requirement = (
            info.requirement_label() if info else tr("release metadata is unavailable")
        )
        return tr(
            "{value0} {value1} cannot be verified for {value2} {value3}. Requires: {value4}. Choose a compatible tool or change the runtime."
        ).format(
            value0=component.label,
            value1=version,
            value2=COMPONENTS[component.runtime].label,
            value3=runtime or "(not selected)",
            value4=requirement,
        )

    def compatible_versions(
        self, name: str, runtimes: dict[str, str]
    ) -> tuple[str, ...]:
        component = COMPONENTS[name]
        runtime = runtimes.get(component.runtime or "")
        if "{java}" in component.image and runtime:
            # Check every candidate image at once rather than one at a time.
            self._check_published(
                component.image.format(version=version, java=runtime)
                for version in self.versions(name)
                if self._info[name][version].supports(runtime)
            )
        return tuple(
            version
            for version in self.versions(name)
            if self.compatibility_issue(name, version, runtimes) is None
        )
