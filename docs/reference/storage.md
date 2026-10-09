# Storage and persistence

## Data directory

The default directory is:

```text
${XDG_DATA_HOME:-~/.local/share}/brig
```

Override it for an invocation with `brig --data-dir DIRECTORY …`. The first load
creates an empty state if none exists.

```text
brig/
├── state.json
├── profiles/
│   └── profile-ENCODED_NAME/
│       ├── revision-1.yaml
│       └── revision-2.yaml
└── runtime/
    └── brig-PROJECT_ID/
        ├── credentials.json
        ├── lifecycle.lock
        └── IMAGE_HASH/
            ├── Dockerfile
            ├── .dockerignore
            ├── compose.yaml
            ├── development.env
            └── SERVICE.env
```

## Definitions

`state.json` contains the storage schema, profiles, revision history, project
registrations, and their snapshots. A project's ID identifies its resources; its
name selects it from the CLI.

Profile folder names are encoded and use the `profile-` prefix. Each revision
produces a separate YAML document with versions written as strings. YAML documents
support reading and sharing, but importing them or applying manual edits to state
is not implemented.

Loading validates the schema and profile/project relationships without internet.
An incompatible or corrupt file produces an error and is not silently replaced.
State and YAML writes use temporary files. If saving a revision fails, its newly
created documents are removed.

## Engine artifacts

The engine generates a directory per Dockerfile and UID/GID hash. Dockerfile
labels include the project name, profile, and revision. Applying another revision
may produce a different image and directory.

The build context excludes every file except the Dockerfile. `compose.yaml` uses
explicit mount paths and does not create a missing source folder. Passwords are
not added to the Dockerfile or profile YAML.

`credentials.json` preserves initialization passwords per service. Service
environment files contain initialization variables; `development.env` contains
connections received by the development container. Generated files have mode
0600. Missing credentials are not regenerated over persistent data.

`lifecycle.lock` coordinates startup and shutdown for the same project. General
state editing still does not coordinate all writers: use one session at a time
when creating, editing, or deleting definitions.

## Docker resources

Names use the `brig-PROJECT_ID` prefix:

| Resource | Name or location |
| --- | --- |
| Development container | `brig-ID-dev` |
| Service container | `brig-ID-SERVICE` |
| Network | `brig-ID-network` |
| Home volume | `brig-ID-home` → `/home/brig` |
| Shared Claude configuration | `brig-claude-UID-SCOPE` → `/home/brig/.config/claude` |
| Claude conversation files | `brig-ID-claude-history` → `/home/brig/.config/claude/projects` |
| Data volume | `brig-ID-SERVICE-data` |
| MongoDB configuration volume | `brig-ID-mongodb-config` |
| Development image | `brig-dev-brig-ID:HASH` |

Source files live in the registered host folder, mounted at `/workspace`. Named
volumes are managed by Docker and are not inside Brig's data directory. They have
ownership labels and, for a service's data, its major version. Existing development
containers with conflicting names are not automatically adopted.

`SCOPE` hashes the engine's absolute runtime directory. All projects in the same
Brig data directory for the same host user share Claude's login, global settings,
and configuration. `CLAUDE_CONFIG_DIR` points Claude at that shared storage. The
volume is external to project Compose lifecycles and has agent, user, and scope
ownership labels. It survives `down` and project deletion; another data directory
or host user gets separate storage. Brig does not mount host agent credentials.

Conversation files in the nested `projects/` directory have a separate volume per
project, preventing histories from colliding at the common `/workspace` path.
The shared directory and history directory are initialized with the unprivileged
user as owner and permissions 0700. Claude manages credential files and refreshes
the login; Brig does not perform authentication or guarantee a token never expires.

The Claude executable lives at `/usr/local/bin/claude` in the image so existing
home volumes do not hide it when containers are recreated.

## What each operation preserves

| Operation | Project registration | Source files | Profile/YAML | Containers/network | Volumes and credentials |
| --- | --- | --- | --- | --- | --- |
| Leave the terminal | Keep | Keep | Keep | Remain running | Keep |
| `down` | Keep | Keep | Keep | Remove | Keep |
| Delete a stopped project | Remove | Keep | Keep | Neither create nor remove | Keep |
| Delete an unreferenced profile | No associated projects | Keep | Remove profile and its YAML | Unchanged | Unchanged |

Deleting a definition does not delete Docker data. Brig does not currently offer
a command to purge volumes or historical artifacts.

## Backups

Keep `state.json`, `profiles/`, `runtime/`, and project source files. For database
data, use consistent backups made with the service's tools: saving Brig files
does not back up Docker volumes.

Restore credentials and data together. Restoring only volumes may leave a database
initialized with passwords that are no longer in local state. Brig refuses to
generate new credentials for those volumes.
