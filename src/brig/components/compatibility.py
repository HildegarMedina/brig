"""Evaluate declared runtime requirements using ecosystem-specific range parsers."""

from dataclasses import dataclass
from functools import lru_cache

from packaging.specifiers import SpecifierSet
from semantic_version import NpmSpec, Version

from brig.i18n import tr


@lru_cache(maxsize=1024)
def matches(requirement: str, runtime: str, dialect: str) -> bool:
    if dialect == "python":
        return SpecifierSet(requirement).contains(runtime, prereleases=False)
    if dialect == "npm":
        return NpmSpec(requirement).match(Version(runtime))
    if dialect == "exact":
        return runtime == requirement
    if dialect == "minimum":
        return tuple(map(int, runtime.split("."))) >= tuple(
            map(int, requirement.split("."))
        )
    raise ValueError(
        tr("Unsupported requirement dialect: {value0}").format(value0=dialect)
    )


@dataclass(frozen=True)
class ReleaseInfo:
    channel: str = "Stable"
    requirements: tuple[str, ...] | None = None
    dialect: str = ""

    def supports(self, runtime: str) -> bool:
        if not self.requirements:
            return False
        for requirement in self.requirements:
            try:
                if matches(requirement, runtime, self.dialect):
                    return True
            except (ValueError, TypeError):
                # Unknown constraints must never become an assumed match.
                continue
        return False

    def requirement_label(self) -> str:
        if not self.requirements:
            return tr("runtime requirements were not published")
        prefix = ">=" if self.dialect == "minimum" else ""
        return " OR ".join(prefix + expression for expression in self.requirements)
