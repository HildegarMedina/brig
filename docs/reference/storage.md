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
├── preferences.json
├── state.json
├── profiles/
│   └── profile-ENCODED_NAME/
│       └── versions/
│           ├── version-1.yaml
│           └── version-2.yaml
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

## Interface preferences

`preferences.json` stores `{"language": "en"}`, `es`, `pt`, or `auto` separately
from profiles and project snapshots. It is created when you save a language choice
in Settings or with `brig language CODE`. Missing preferences follow the terminal
locale. `--data-dir` also selects the preference directory; `--lang` and
`BRIG_LANG` override the saved choice without changing the file. Saving is atomic;
a failed write preserves the previous preference.

## Definitions

`state.json` contains the storage schema, profiles, version history, project
registrations, and their snapshots. A project's ID identifies its resources; its
name selects it from the CLI.

Profile folder names are encoded and use the `profile-` prefix. Each version
produces a separate YAML document under `versions/`, with component releases
written as strings. Share copies of these documents and import them with
`brig profile import PATH [PATH ...]`. Files and folders are supported, including
complete histories and inherited profiles. Manual edits to `state.json` are not
an import workflow; see [import profiles](../how-to/import-profiles.md).

New state and YAML documents use schema version 2. Profiles store their history
as `versions`; YAML uses `version: N`. The reader accepts schema 1 state. At the
next successful save, Brig writes schema 2 and creates documents in the new
layout, checking any original YAML before copying it. Original legacy YAML files
are retained unchanged. Keep a backup before switching to an older Brig release,
which cannot read the newer schema.

Inherited profile versions include an `extends` reference with a base profile
name and a fixed version number. They also retain the full resolved configuration
for portable review and existing project snapshots. Loading validates references,
cycles, and preservation of inherited selections offline. A base cannot be deleted
while any saved child version references it. Updating the base of a child is an
explicit operation that creates a new child version; Docker does not resolve
profile inheritance at runtime.

Loading validates the schema and profile/project relationships without internet.
An incompatible or corrupt file produces an error and is not silently replaced.
State and YAML writes use temporary files. If saving a version fails, its newly
created documents are removed. Import validates the complete batch before a
single save, preserving previous definitions on validation or save failure.
Existing versions cannot be overwritten. Imported schema 1 YAML is accepted and
written in the current schema 2 format; source files remain unchanged.

## Engine artifacts

The engine generates a directory per Dockerfile and UID/GID hash. Dockerfile
labels include the project name, profile, and version. Applying another version
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

## Project context and attachments

Each project's existing `/workspace` mount exposes its local context folder:

```text
PROJECT_FOLDER/
└── .brig/
    └── context/
        ├── .gitignore
        ├── design-notes.md
        └── attachments/
            └── brig-UNIQUE_ID/
                └── screenshot.png
```

`brig project attach NAME FILE [FILE ...]` creates independent copies and prints
their `/workspace/.brig/context/attachments/…` paths. No new Docker mount, image
build, or state-schema migration is needed. Files belong to this project and are
accessible to its agents through the normal writable workspace mount.

`attachments/` is reserved for disposable copies. `project detach NAME` and a
successful project shutdown remove that directory while preserving original
source files and permanent context such as `design-notes.md`. Leaving an agent
or shell does not trigger cleanup. Files have no timed expiry; clean up explicitly
after an interrupted session. Removing files does not remove agent history.

The first attachment creates context's `.gitignore` with `*` if none exists,
without changing the project's main `.gitignore`. Existing context ignore rules
and tracked files are kept. Context paths that are symlinks or non-directories
are rejected to avoid copying or removing files outside the reserved location.

## Docker resources

Names use the `brig-PROJECT_ID` prefix:

| Resource | Name or location |
| --- | --- |
| Development container | `brig-ID-dev` |
| Agent container | `brig-ID-agent-AGENT` |
| Service container | `brig-ID-SERVICE` |
| Network | `brig-ID-network` |
| Agent home volume | `brig-ID-AGENT-home` → `/home/brig` in that agent container |
| Home volume | `brig-ID-home` → `/home/brig` |
| Shared Claude configuration | `brig-claude-UID-SCOPE` → `/home/brig/.config/claude` |
| Claude conversation files | `brig-ID-claude-history` → `/home/brig/.config/claude/projects` |
| Data volume | `brig-ID-SERVICE-data` |
| MongoDB configuration volume | `brig-ID-mongodb-config` |
| Development image | `brig-dev-brig-ID:HASH` |
| Agent image | `brig-dev-brig-ID:HASH-agent-AGENT` |

Source files live in the registered host folder, mounted at `/workspace`. Named
volumes are managed by Docker and are not inside Brig's data directory. They have
ownership labels and, for a service's data, its major version. Existing development
containers with conflicting names are not automatically adopted.

`SCOPE` hashes the engine's absolute runtime directory. All projects in the same
Brig data directory for the same host user share each selected agent's login and
global configuration. Each agent has its own external volume named
`brig-AGENT-UID-SCOPE`, with agent, user, and scope ownership labels. It survives
`down` and project deletion; another data directory or host user gets separate
storage. Brig does not mount host agent credentials. Only the matching agent
container mounts that volume. Development has no agent credential mounts, and
agent containers never share their home volume. They share the writable project
folder and project network.

| Agent | Shared storage | Project-specific conversation storage |
| --- | --- | --- |
| Claude | `/home/brig/.config/claude` (`CLAUDE_CONFIG_DIR`) | Nested `projects/` volume |
| Codex | `/home/brig/.config/codex` (`CODEX_HOME`), including `auth.json` | Nested `sessions/` and `archived_sessions/` volumes; SQLite databases and logs under `/home/brig/.local/state/codex` in the private home volume |
| OpenCode | `/home/brig/.local/share/opencode`, including `auth.json` and `config/` (`OPENCODE_CONFIG_DIR`) | SQLite database at `/home/brig/.local/state/opencode/brig.db` (`OPENCODE_DB`) in the private home volume; nested `project/` and legacy `storage/` volumes |

The first nested volume is named `brig-ID-AGENT-history`; additional directories
use `brig-ID-AGENT-history-2`. Shared directories and nested history directories
are owned by the unprivileged user with permissions 0700. Codex uses file-based
credential storage so its login can be shared without a host keyring. Agents
manage credentials and token refresh; Brig does not guarantee a login never expires.

Agent executables and their installation resources live outside `/home/brig`,
so persistent home volumes do not hide them when containers are recreated.
Login and nested conversation-directory volume names are unchanged by agent
separation. Existing local SQLite databases and logs in the legacy development
home are preserved there but are not automatically copied to the new agent homes.
See [upgrade guidance](../how-to/agent-isolation.md#upgrade-existing-projects).

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
