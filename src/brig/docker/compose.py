"""Compose definitions for one pinned project, without host-published databases."""

import json
import re
from pathlib import Path

from brig.components.agents import AGENTS, validate_agents
from brig.components.catalog import validate_selection
from brig.docker.auth_proxy import add_credential_proxy
from brig.docker.services import SERVICES
from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Project


def project_prefix(project: Project) -> str:
    # Stored IDs are validated as strings; never use an unchecked ID as a path.
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", project.id):
        raise BrigError(tr("Cannot use this project with Docker: invalid project ID."))
    return f"brig-{project.id.lower()}"


def agent_history_volumes(
    project: Project, agent: str
) -> tuple[tuple[str, str, str], ...]:
    integration = AGENTS[agent]
    return tuple(
        (
            f"{agent}_history" + (f"_{index + 1}" if index else ""),
            f"{project_prefix(project)}-{agent}-history"
            + (f"-{index + 1}" if index else ""),
            f"{integration.config_directory}/{directory}",
        )
        for index, directory in enumerate(integration.history_directories)
    )


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


def compose_definition(
    project: Project, image: str, uid: int, gid: int, *, agent_volumes=None
) -> dict:
    configuration = project.configuration
    validate_agents(configuration.selected_agents, configuration.agent)
    validate_selection(
        configuration.runtimes,
        configuration.tools,
        configuration.services,
        configuration.agent,
    )
    if not project.path or not Path(project.path).is_dir():
        raise BrigError(
            tr(
                "Project folder is missing: {value0}. Register an existing folder with 'brig project init'."
            ).format(value0=project.path or "(not registered)")
        )
    prefix = project_prefix(project)
    labels = {"org.brig.project-id": project.id}
    services = {
        "dev": {
            "image": image,
            "build": {
                "context": ".",
                "dockerfile": "Dockerfile",
                "target": "dev",
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
    networks = {
        "default": {"name": f"{prefix}-network", "labels": labels},
        "credential_egress": {"name": f"{prefix}-credential-egress", "labels": labels},
    }
    add_agent_storage(
        project, services, volumes, networks, labels, uid, gid, agent_volumes
    )
    dependencies = {}
    for name, version in sorted(configuration.services.items()):
        add_database_service(services, volumes, name, version, prefix, labels)
        dependencies[name] = {"condition": "service_healthy"}
    if dependencies:
        services["dev"].setdefault("depends_on", {}).update(dependencies)
    return {
        "name": prefix,
        "services": services,
        "volumes": volumes,
        "networks": networks,
    }


def render_compose(
    project: Project, image: str, uid: int, gid: int, *, agent_volumes=None
) -> str:
    definition = compose_definition(
        project, image, uid, gid, agent_volumes=agent_volumes
    )
    rendered = yaml_document(definition)
    return (
        "# Generated by Brig; database ports stay inside this project's network.\n"
        + rendered
    )


def add_database_service(services, volumes, name, version, prefix, labels) -> None:
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


def add_agent_storage(
    project, services, volumes, networks, labels, uid, gid, agent_volumes
) -> None:
    agent = project.configuration.agent
    integration = AGENTS[agent]
    home = "home"
    volumes[home] = {
        "name": f"{project_prefix(project)}-{agent}-runtime-home",
        "labels": labels,
    }
    service = services["dev"]
    service["labels"] = {**labels, "org.brig.agent": agent}
    if not integration.config_directory:
        return
    shared = f"{agent}_config"
    volumes[shared] = {
        "name": (agent_volumes or {}).get(agent, f"brig-{agent}-{uid}"),
        "external": True,
    }
    service["brig_auth_config"] = integration.config_directory
    add_credential_proxy(
        agent,
        service,
        services,
        volumes,
        networks,
        project_prefix(project),
        services["dev"]["image"],
        uid,
        gid,
        shared,
    )
    for history, volume, target in agent_history_volumes(project, agent):
        volumes[history] = {"name": volume, "labels": labels}
        service["volumes"].append(
            {"type": "volume", "source": history, "target": target}
        )
