"""Safe, strict reading of portable profile YAML and version directories."""

from pathlib import Path

import yaml

from brig.components.catalog import SERVICES
from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Profile
from brig.persistence.codec import decode_profile_version, validate_name

MAX_DOCUMENT_BYTES = 1024 * 1024


class ProfileLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError(tr("YAML aliases are not supported in profiles."))
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError(tr("Profile mapping keys must be strings."))
            if key in mapping:
                raise ValueError(tr("Duplicate YAML key: {value0}.").format(value0=key))
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def read_profile(path: Path) -> Profile:
    try:
        with path.open("rb") as stream:
            content = stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError(tr("Profile YAML exceeds the 1 MiB size limit."))
        raw = yaml.load(content.decode("utf-8"), Loader=ProfileLoader)
        if not isinstance(raw, dict):
            raise ValueError(tr("Expected one profile mapping."))
        schema = raw.get("schema_version")
        if type(schema) is not int or schema not in (1, 2):
            raise ValueError(tr("Unsupported profile schema version."))
        version_field = "revision" if schema == 1 and "revision" in raw else "version"
        required = {
            "schema_version",
            "name",
            version_field,
            "runtimes",
            "tools",
            "databases",
            "caches",
            "agent",
        }
        if not required.issubset(raw) or set(raw) - required - {"agents", "extends"}:
            raise ValueError(tr("Missing or unknown profile fields."))
        validate_name(raw["name"])
        services = {}
        for section in ("databases", "caches"):
            if not isinstance(raw[section], dict):
                raise ValueError(
                    tr("{value0} must be a version mapping.").format(value0=tr(section))
                )
            for name, version in raw[section].items():
                component = SERVICES.get(name)
                if component is None or (
                    component.category == "Caches / key-value stores"
                ) != (section == "caches"):
                    raise ValueError(
                        tr("Unsupported {value0} component: {value1}.").format(
                            value0=tr(section), value1=name
                        )
                    )
                services[name] = version
        version = decode_profile_version(
            {
                "number": raw[version_field],
                "runtimes": raw["runtimes"],
                "tools": raw["tools"],
                "services": services,
                "agent": raw["agent"],
                "agents": raw.get("agents"),
                "extends": raw.get("extends"),
            }
        )
        return Profile(raw["name"], [version])
    except OSError as error:
        raise BrigError(
            tr("Cannot read profile {value0}: {value1}").format(
                value0=path, value1=error
            )
        ) from error
    except (
        yaml.YAMLError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
        BrigError,
    ) as error:
        raise BrigError(
            tr("Invalid profile YAML in {value0}: {value1}").format(
                value0=path, value1=error
            )
        ) from error


def read_profiles(paths: list[Path]) -> list[Profile]:
    documents = []
    for path in paths:
        path = path.expanduser()
        try:
            files = (
                sorted(
                    file
                    for file in path.rglob("*")
                    if file.is_file() and file.suffix.lower() in (".yaml", ".yml")
                )
                if path.is_dir()
                else [path]
            )
        except OSError as error:
            raise BrigError(
                tr("Cannot scan profile folder {value0}: {value1}").format(
                    value0=path, value1=error
                )
            ) from error
        if not files:
            raise BrigError(
                tr("No profile YAML files found in {value0}.").format(value0=path)
            )
        documents.extend(read_profile(file) for file in files)
    if not documents:
        raise BrigError(tr("Import needs at least one profile YAML file or folder."))
    return documents
