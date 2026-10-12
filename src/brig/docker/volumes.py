"""Volume ownership, service-major validation and shared agent storage."""

import hashlib
import json
from pathlib import Path

from brig.components.agents import AGENTS
from brig.docker.client import DockerClient
from brig.docker.compose import project_prefix
from brig.errors import BrigError
from brig.i18n import tr
from brig.models import Project


class DockerVolumes:
    def __init__(self, client: DockerClient, directory: Path, uid: int):
        self.client = client
        self.uid = uid
        self.agent_scope = hashlib.sha256(
            str(directory.resolve()).encode()
        ).hexdigest()[:12]

    def agent_volume_name(self, agent: str) -> str:
        return f"brig-{agent}-{self.uid}-{self.agent_scope}"

    def check_data_versions(self, project):
        for name, version in project.configuration.services.items():
            volume = f"{project_prefix(project)}-{name}-data"
            result = self.client.run(["volume", "inspect", volume], check=False)
            if result.returncode and "no such" in (result.stderr or "").lower():
                continue
            if result.returncode:
                raise BrigError(
                    tr("Cannot inspect project data volume: ")
                    + (result.stderr or "").strip()
                )
            try:
                labels = json.loads(result.stdout)[0].get("Labels") or {}
                if labels.get("org.brig.project-id") != project.id:
                    raise BrigError(
                        tr(
                            "Data volume '{value0}' is not managed by this project."
                        ).format(value0=volume)
                    )
                if labels.get("org.brig.service-major") != version.split(".")[0]:
                    raise BrigError(
                        tr(
                            "Cannot start {value0} {value1} with this project's existing data volume. A major-version data migration is required; Brig will not overwrite or reinitialize it."
                        ).format(value0=name, value1=version)
                    )
            except (ValueError, IndexError, KeyError, TypeError) as error:
                raise BrigError(
                    tr("Docker returned an invalid data volume description.")
                ) from error

    def ensure_agent_volumes(self, project: Project) -> None:
        for agent in project.configuration.selected_agents:
            if not AGENTS[agent].config_directory:
                continue
            name = self.agent_volume_name(agent)
            labels = {
                "org.brig.agent": agent,
                "org.brig.agent-scope": self.agent_scope,
                "org.brig.uid": str(self.uid),
            }
            found = self.client.run(["volume", "inspect", name], check=False)
            if found.returncode:
                if "no such" not in (found.stderr or "").lower():
                    raise BrigError(
                        tr("Cannot inspect shared agent storage: ")
                        + (found.stderr or "").strip()
                    )
                self.client.run(
                    [
                        "volume",
                        "create",
                        *[
                            argument
                            for key, value in labels.items()
                            for argument in ("--label", f"{key}={value}")
                        ],
                        name,
                    ]
                )
                found = self.client.run(["volume", "inspect", name])
            try:
                actual = json.loads(found.stdout)[0].get("Labels") or {}
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise BrigError(
                    tr("Docker returned invalid shared agent storage information.")
                ) from error
            if any(actual.get(key) != value for key, value in labels.items()):
                raise BrigError(
                    tr(
                        "Shared agent volume '{value0}' is not owned by this Brig installation."
                    ).format(value0=name)
                )
