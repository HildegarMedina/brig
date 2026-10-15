# Manage a project

Commands act on one project. They do not start every registered project. Use its
name with `run` or `--project` with other commands. Within a registered folder or
one of its subfolders, Brig can detect the project; for nested projects, the
nearest registered parent takes precedence.

## Start and enter

```bash
brig run my-api
```

This command builds the image if missing, starts the profile's services, waits for
their healthchecks, and opens the development terminal. It reuses an existing
compatible environment.

To start the environment without entering:

```bash
brig up --project my-api
```

You can also enter with:

```bash
brig shell --project my-api
```

Both `run` and `shell` prepare the environment before opening the terminal. `exit`
returns to the host and keeps the containers running.

## Execute a program without an interactive terminal

```bash
brig run my-api --command python --version
brig run my-api --command python -m unittest
```

Everything after `--command` belongs to the program. Brig passes arguments directly
to Docker without interpreting them as shell code. If you need a shell, explicitly
use `--command bash -lc 'your command'`.

The program works at `/workspace` and uses the container user. Finishing the
program keeps the environment running.

## Share images and context with an agent

From a host terminal inside a registered project folder or one of its subfolders,
attach one or more local files without specifying the project:

```bash
brig attach ~/Downloads/design.png ~/Documents/requirements.txt
```

From another folder, or to choose a different project, use `--project`:

```bash
brig attach ~/Downloads/design.png --project my-api
```

Relative file paths are resolved from your current folder. Nested registered
projects select the nearest containing project. The existing
`brig project attach my-api FILE...` command remains supported.

Brig keeps the originals and prints the paths to independent copies, for example:

```text
/workspace/.brig/context/attachments/brig-EXAMPLE/design.png
/workspace/.brig/context/attachments/brig-OTHER/requirements.txt
```

Use the actual returned path in your agent's prompt: "Build the interface using
the image at `/workspace/.brig/context/attachments/brig-EXAMPLE/design.png`."
Brig also tells Claude Code, Codex, and OpenCode where attachments and context
live, so they can look there when you mention a file by name only. The returned
path stays the most precise reference, especially when names repeat.
Files are available immediately through the existing project mount, including
when Claude, Codex, or OpenCode is already running. Supported document and image
formats depend on the agent. Attaching a file does not submit it to the chat.

To keep reusable context, place it directly in your project's `.brig/context/`
folder, outside the reserved `attachments/` directory. The first attachment
creates a `.gitignore` inside the context folder that ignores its contents;
existing context ignore rules are preserved. Already tracked files remain tracked.

Remove all attachment copies when finished:

```bash
brig detach
```

Like `attach`, this detects the project from its folder or subfolders. Use
`brig detach --project my-api` from another folder. `brig dettach` is accepted as
an alias; `brig project detach my-api` remains supported. Only attachment copies
are removed; originals, permanent context, and project references stay intact.

A successful `brig down --project my-api` also cleans attachments. Leaving an
agent or shell keeps the environment and attachments available. Original files
and permanent context remain untouched. Cleanup does not erase content already
stored in an agent conversation. After an interrupted session, use `detach` or
`down` explicitly to clean up.

## Consult another project without copying it

Register an existing local folder as a read-only reference:

```bash
brig reference add ~/projects/old-api --project my-api --as legacy
brig reference list --project my-api
```

Inside `my-api`, `--project my-api` is optional. `--as` defaults to the resolved
folder name; aliases use kebab-case, such as `legacy-api`. References appear at
`/references/ALIAS`, separate from the editable project at `/workspace`.
The source must be outside the active project and its parent folders.

Brig mounts the original directory read-only, without copying its files or
changing its permissions. Host edits become visible immediately. The agent's
user must already have permission to read the source files and traverse its
directories; Brig does not grant access by modifying the reference's ACLs.

Claude Code, Codex, and OpenCode receive sandbox instructions listing each
mounted reference. They are told to search `/references` when consulting legacy
code, use it to understand previous behavior and patterns, and make changes in
`/workspace`. Instructions in reference projects do not override the sandbox or
active project requirements. For example: "Compare our login with legacy."

Adding or removing a reference only saves configuration. If the environment is
stopped, the next `brig up` or `brig run` applies it. If it is running, the current
mounts and sessions stay intact. Interactive `brig run` detects the pending
changes and asks whether to apply them and enter. The prompt warns that all
existing work-container sessions will close; the default is No. Accepting applies
the references and then opens the selected agent. Declining or cancelling leaves
the running environment and pending configuration intact without entering.
`--no-input` and non-interactive invocations report the pending changes without
prompting or restarting anything. The same confirmation is available when entering
Bash, a shell, an agent, or an explicit command from an interactive terminal.

You can also close your work sessions and explicitly apply the configuration:

```bash
brig reference apply --project my-api
```

This recreates only the work container, ending any sessions still inside it.
Database services and persistent volumes remain in place. Reference changes do
not change the image cache key; existing matching images are reused. Updating
Brig itself may require its usual image rebuild once for new sandbox guidance.
Stopping and starting the environment also applies pending changes.

To unlink a reference:

```bash
brig reference remove legacy --project my-api
```

Original files remain untouched. A running container keeps its old mount until
`reference apply` or a stop/start; removing configuration does not instantly revoke
an existing mount. References persist across `down` and are not removed by
`project detach`. If a source disappears or is replaced by a symlink to another
folder, the next apply/start fails with a diagnostic; remove the reference or
register its new location explicitly. Reference paths belong to the machine
running the Docker daemon, like the main workspace bind mount.

## Use the profile's databases and message brokers

Services are reachable by name within the project's network:

| Service | Host | Internal port | Development container variables |
| --- | --- | --- | --- |
| PostgreSQL | `postgresql` | 5432 | `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` |
| MySQL | `mysql` | 3306 | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` |
| MariaDB | `mariadb` | 3306 | `MARIADB_HOST`, `MARIADB_PORT`, `MARIADB_DATABASE`, `MARIADB_USER`, `MARIADB_PASSWORD` |
| MongoDB | `mongodb` | 27017 | `MONGODB_URI` |
| Redis | `redis` | 6379 | `REDIS_HOST`, `REDIS_PORT`, `REDIS_URL` |
| RabbitMQ | `rabbitmq` | 5672 (AMQP), 15672 (HTTP API) | `AMQP_URL`, `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `RABBITMQ_MANAGEMENT_URL` |
| Kafka | `kafka` | 9092 | `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_HOST`, `KAFKA_PORT` |

Brig creates initial credentials per project and preserves them. PostgreSQL,
MySQL, and MariaDB have an initial database named `brig`; MongoDB uses
authentication in `admin` and a URI targeting `brig`. Redis does not require a
password in this configuration and does not publish ports on the host.

RabbitMQ uses the default virtual host `/` with the project's `brig` user, and
includes the management plugin: its HTTP API is reachable from the development
container at `RABBITMQ_MANAGEMENT_URL` with the same credentials. Kafka runs as
a single KRaft node (broker and controller) with plaintext listeners and no
authentication, so topics must use a replication factor of 1. The container
advertises itself as `kafka:9092`, which is only reachable inside the project
network.

Brig also tells agents that they run in an isolated sandbox. These services are
private to the project environment and are not the databases, Redis, or other
services your application uses outside Brig. Agents should use these variables
instead of hosts or credentials described in `CLAUDE.md`, the README, `.env`
files, or test configuration. Claude Code receives this guidance in its system
prompt and Codex as developer instructions; both outrank project `CLAUDE.md` and
`AGENTS.md` files. For Codex, this replaces any `developer_instructions` set in
its `config.toml`. OpenCode receives it as an extra `instructions` file, added to
your own configuration and placed after project `AGENTS.md` files in the same
system prompt. The guidance names the variables, not their values, so passwords
do not end up in the agent conversation.

Configure your application to use these variables. Brig does not modify its
`.env` file. PHP receives PDO MySQL for MySQL/MariaDB and PDO PostgreSQL for
PostgreSQL. PHP extensions for MongoDB, Redis, RabbitMQ, and Kafka are not
installed automatically.

## Create an inherited profile

```bash
brig profile create --base python-dev --base-version 1
```

Name the new profile and select its additional components. The wizard shows the
base configuration separately and offers only runtimes, tools, services, and
agents that are not inherited. You can also run `brig profile create` and choose
the base interactively. A child may inherit another child; cycles are rejected.

Changing `python-dev` leaves the child pinned to version 1. To explicitly adopt
the latest base version:

```bash
brig profile edit my-child-profile --update-base
```

Review the inherited configuration and the child's own additions, then save its
new version. Projects still require their usual explicit `project update`.
Inherited components cannot be removed or overridden in the child. A profile
referenced as a base by any saved child version cannot be deleted; remove its
dependent child profiles first, after their projects no longer reference them.

## Update a profile used by a project

```bash
brig profile edit python-dev
brig down --project my-api
brig project update my-api
brig run my-api
```

Editing a profile creates another version. The project keeps its previous
version until you run `project update`, which adopts the latest version of its
profile. The next execution generates the corresponding configuration.

Changing a service's major version when it has persistent data requires a data
migration. Brig detects this through volume labels and rejects automatic reuse.
It does not migrate or reinitialize that data.

## Clean old project images

After updating an environment, remove unused images from earlier configurations:

```bash
brig project clean my-api
```

Brig keeps images for the current configuration and any image used by a running
or stopped container from any project. It removes unused shared development and
credential proxy image tags, plus legacy image tags belonging to this project,
without forcing deletion. Shared images with no containers can be rebuilt when
another project next needs them. You can run cleanup
while the project is running.

Source files, volumes, database images, and build cache remain intact. Cleanup
reports how many tags were removed; shared layers mean this is not a measurement
of reclaimed disk space. Older generated configuration files are also retained.

## View or export the Dockerfile

```bash
brig project dockerfile my-api
```

To save a copy, from the project folder:

```bash
brig project dockerfile --output .brig/Dockerfile
```

Export works without Docker or internet and refuses existing files. The engine
generates its own copy under Brig's data directory. Editing an exported copy does
not change the Dockerfile used by `run`.

## Rename a definition

```bash
brig project rename my-api backend
brig profile rename python-dev python
```

Renaming changes only the name. Docker resources are named by the project's
internal ID, so containers, images, and volumes are kept, and a running project
keeps running. A renamed profile's projects and child profiles follow the new
name; its YAML documents move to the new profile folder.

## Stop or delete a definition

```bash
brig down --project my-api
brig project delete my-api
```

`down` removes containers, the network, and attachment copies while preserving
volumes and permanent context. Deleting a project stops it if needed and removes
its containers, networks, images, volumes (including databases and agent
history), runtime files, and Brig registration. Its folder, code, and profile are
kept, as are the agent logins shared with other projects.

A profile can only be deleted when no projects reference it:

```bash
brig profile delete python-dev
```

Both deletion confirmations default to **Cancel**. `--yes` skips confirmation for
scripts but retains validation.
