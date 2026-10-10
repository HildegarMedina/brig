"""On-demand release discovery, cached only for one profile operation."""

import re
from collections.abc import Callable
from urllib.error import URLError

from brig.components.catalog import COMPONENTS
from brig.components.compatibility import ReleaseInfo
from brig.components.providers import PROVIDERS, fetch_text, release_info, source_label
from brig.errors import BrigError


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
                f"Cannot fetch versions for {component.label} from {source_label(component)}: {error}. "
                "Check your connection and retry. No fallback versions were selected."
            ) from error
        self._snapshot[name] = result
        self._info[name] = info
        return result

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
