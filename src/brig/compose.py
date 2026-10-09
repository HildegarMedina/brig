"""Compose definitions for one pinned project, without host-published databases."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from brig.catalog import validate_selection
from brig.errors import BrigError
from brig.models import Project


@dataclass(frozen=True)
class ServiceDefinition:
    image: str
    data: str
    health: tuple[str, ...]


SERVICES = {
    "postgresql": ServiceDefinition(
        "postgres",
        "/var/lib/postgresql/data",
        ("CMD-SHELL", 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'),
    ),
    "mysql": ServiceDefinition(
        "mysql",
        "/var/lib/mysql",
        (
            "CMD-SHELL",
            'mysqladmin ping -h 127.0.0.1 -uroot -p"$MYSQL_ROOT_PASSWORD" --silent',
        ),
    ),
    "mariadb": ServiceDefinition(
        "mariadb",
        "/var/lib/mysql",
        ("CMD", "healthcheck.sh", "--connect", "--innodb_initialized"),
    ),
    "mongodb": ServiceDefinition(
        "mongo",
        "/data/db",
        (
            "CMD",
            "mongosh",
            "--quiet",
            "--eval",
            "quit(db.adminCommand('ping').ok ? 0 : 1)",
        ),
    ),
    "redis": ServiceDefinition("redis", "/data", ("CMD", "redis-cli", "ping")),
}


def project_prefix(project: Project) -> str:
    # Stored IDs are validated as strings; never use an unchecked ID as a path.
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", project.id):
        raise BrigError("Cannot use this project with Docker: invalid project ID.")
    return f"brig-{project.id.lower()}"


def yaml_document(value, indent=0) -> str:
    """Emit the small JSON-compatible YAML subset needed by Compose."""

    def scalar(item):
        if isinstance(item, str):
            # Compose interpolation must not interpret paths or shell variables.
            item = item.replace("$", "$$")
        return json.dumps(item, ensure_ascii=True)

    lines = []
    for key, item in value.items():
        prefix = " " * indent + key + ":"
        if isinstance(item, dict) and item:
            lines.append(prefix)
            lines.append(yaml_document(item, indent + 2).rstrip())
        else:
            if isinstance(item, list):
                if any(isinstance(entry, dict) for entry in item):
                    lines.append(prefix)
                    for entry in item:
                        block = yaml_document(entry, indent + 4).splitlines()
                        lines.append(" " * (indent + 2) + "- " + block[0].lstrip())
                        lines.extend(block[1:])
                    continue
                encoded = "[" + ", ".join(scalar(entry) for entry in item) + "]"
            else:
                encoded = scalar(item)
            lines.append(prefix + " " + encoded)
    return "\n".join(lines) + "\n"


def compose_definition(project: Project, image: str, uid: int, gid: int) -> dict:
    revision = project.configuration
    validate_selection(
        revision.runtimes, revision.tools, revision.services, revision.agent
    )
    if not project.path or not Path(project.path).is_dir():
        raise BrigError(
            f"Project folder is missing: {project.path or '(not registered)'}. Register an existing folder with 'brig project init'."
        )
    prefix = project_prefix(project)
    labels = {"org.brig.project-id": project.id}
    services = {
        "dev": {
            "image": image,
            "build": {
                "context": ".",
                "dockerfile": "Dockerfile",
                "args": {"BRIG_UID": str(uid), "BRIG_GID": str(gid)},
            },
            "container_name": f"{prefix}-dev",
            "labels": labels,
            "init": True,
            "stdin_open": True,
            "tty": True,
            "env_file": ["development.env"],
            "volumes": [
                {
                    "type": "bind",
                    "source": project.path,
                    "target": "/workspace",
                    "bind": {"create_host_path": False},
                },
                {"type": "volume", "source": "home", "target": "/home/brig"},
            ],
        }
    }
    volumes = {"home": {"name": f"{prefix}-home", "labels": labels}}
    dependencies = {}
    for name, version in sorted(revision.services.items()):
        definition = SERVICES[name]
        data = definition.data
        health = definition.health
        if name == "postgresql" and int(version.split(".")[0]) >= 18:
            data = "/var/lib/postgresql"
        if name == "mongodb" and int(version.split(".")[0]) < 5:
            health = tuple("mongo" if entry == "mongosh" else entry for entry in health)
        services[name] = {
            "image": f"{definition.image}:{version}",
            "container_name": f"{prefix}-{name}",
            "labels": labels,
            "env_file": [f"{name}.env"],
            "volumes": [f"{name}_data:{data}"],
            "healthcheck": {
                "test": list(health),
                "interval": "5s",
                "timeout": "5s",
                "retries": 60,
                "start_period": "30s",
            },
        }
        if name == "mongodb":
            services[name]["volumes"].append("mongodb_config:/data/configdb")
            volumes["mongodb_config"] = {
                "name": f"{prefix}-mongodb-config",
                "labels": labels,
            }
        if name == "redis":
            services[name]["command"] = ["redis-server", "--appendonly", "yes"]
        volumes[f"{name}_data"] = {
            "name": f"{prefix}-{name}-data",
            "labels": {**labels, "org.brig.service-major": version.split(".")[0]},
        }
        dependencies[name] = {"condition": "service_healthy"}
    if dependencies:
        services["dev"]["depends_on"] = dependencies
    return {
        "name": prefix,
        "services": services,
        "volumes": volumes,
        "networks": {"default": {"name": f"{prefix}-network", "labels": labels}},
    }


def render_compose(project: Project, image: str, uid: int, gid: int) -> str:
    definition = compose_definition(project, image, uid, gid)
    rendered = yaml_document(definition)
    return (
        "# Generated by Brig; database ports stay inside this project's network.\n"
        + rendered
    )


def service_environment(
    name: str, password: str, root_password: str
) -> tuple[dict, dict]:
    """Return container initialization and developer connection variables."""
    if name == "postgresql":
        return (
            {
                "POSTGRES_USER": "brig",
                "POSTGRES_DB": "brig",
                "POSTGRES_PASSWORD": password,
            },
            {
                "PGHOST": name,
                "PGPORT": "5432",
                "PGUSER": "brig",
                "PGDATABASE": "brig",
                "PGPASSWORD": password,
            },
        )
    if name in ("mysql", "mariadb"):
        prefix = name.upper()
        return (
            {
                f"{prefix}_DATABASE": "brig",
                f"{prefix}_USER": "brig",
                f"{prefix}_PASSWORD": password,
                f"{prefix}_ROOT_PASSWORD": root_password,
            },
            {
                f"{prefix}_HOST": name,
                f"{prefix}_PORT": "3306",
                f"{prefix}_DATABASE": "brig",
                f"{prefix}_USER": "brig",
                f"{prefix}_PASSWORD": password,
            },
        )
    if name == "mongodb":
        return (
            {
                "MONGO_INITDB_ROOT_USERNAME": "brig",
                "MONGO_INITDB_ROOT_PASSWORD": password,
            },
            {
                "MONGODB_URI": f"mongodb://brig:{password}@mongodb:27017/brig?authSource=admin"
            },
        )
    return (
        {},
        {
            "REDIS_HOST": "redis",
            "REDIS_PORT": "6379",
            "REDIS_URL": "redis://redis:6379",
        },
    )
