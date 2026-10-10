"""Preserve and extend project database credentials without reinitializing data."""

import json
import secrets

from brig.docker.client import DockerClient
from brig.docker.workspace import DockerWorkspace
from brig.errors import BrigError
from brig.i18n import tr


class DatabaseCredentials:
    def __init__(self, client: DockerClient, workspace: DockerWorkspace):
        self.client = client
        self.workspace = workspace

    def load(self, project):
        path = self.workspace.project_directory(project) / "credentials.json"
        if path.exists():
            try:
                credentials = json.loads(path.read_text())
                if not isinstance(credentials, dict) or any(
                    not isinstance(pair, dict)
                    or set(pair) != {"password", "root_password"}
                    or any(
                        not isinstance(value, str)
                        or not value.isalnum()
                        or len(value) < 24
                        for value in pair.values()
                    )
                    for pair in credentials.values()
                ):
                    raise ValueError(tr("Invalid credentials"))
            except (OSError, ValueError) as error:
                raise BrigError(
                    tr(
                        "Cannot read project database credentials. Restore credentials.json from backup; passwords will not be silently replaced."
                    )
                ) from error
        else:
            credentials = {}
            # Existing volumes without credentials cannot be safely reinitialized.
            result = self.client.run(
                [
                    "volume",
                    "ls",
                    "--filter",
                    f"label=org.brig.project-id={project.id}",
                    "--format",
                    "{{.Name}}",
                ]
            )
            if result.stdout.strip():
                raise BrigError(
                    tr(
                        "Project volumes exist but database credentials are missing. Restore the project's credentials.json before starting it."
                    )
                )
        changed = not path.exists()
        for name in project.configuration.services:
            if name not in credentials:
                credentials[name] = {
                    "password": secrets.token_hex(24),
                    "root_password": secrets.token_hex(24),
                }
                changed = True
        if changed:
            self.workspace.write(path, json.dumps(credentials, indent=2) + "\n")
        return credentials
