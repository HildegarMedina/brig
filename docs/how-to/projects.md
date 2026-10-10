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

From a host terminal, attach one or more local files:

```bash
brig project attach my-api ~/Downloads/design.png ~/Documents/requirements.txt
```

Brig keeps the originals and prints the paths to independent copies, for example:

```text
/workspace/.brig/context/attachments/brig-EXAMPLE/design.png
/workspace/.brig/context/attachments/brig-OTHER/requirements.txt
```

Use the actual returned path in your agent's prompt: "Build the interface using
the image at `/workspace/.brig/context/attachments/brig-EXAMPLE/design.png`."
Files are available immediately through the existing project mount, including
when Claude, Codex, or OpenCode is already running. Supported document and image
formats depend on the agent. Attaching a file does not submit it to the chat.

To keep reusable context, place it directly in your project's `.brig/context/`
folder, outside the reserved `attachments/` directory. The first attachment
creates a `.gitignore` inside the context folder that ignores its contents;
existing context ignore rules are preserved. Already tracked files remain tracked.

Remove all attachment copies when finished:

```bash
brig project detach my-api
```

A successful `brig down --project my-api` also cleans attachments. Leaving an
agent or shell keeps the environment and attachments available. Original files
and permanent context remain untouched. Cleanup does not erase content already
stored in an agent conversation. After an interrupted session, use `detach` or
`down` explicitly to clean up.

## Use the profile's databases

Services are reachable by name within the project's network:

| Service | Host | Internal port | Development container variables |
| --- | --- | --- | --- |
| PostgreSQL | `postgresql` | 5432 | `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` |
| MySQL | `mysql` | 3306 | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` |
| MariaDB | `mariadb` | 3306 | `MARIADB_HOST`, `MARIADB_PORT`, `MARIADB_DATABASE`, `MARIADB_USER`, `MARIADB_PASSWORD` |
| MongoDB | `mongodb` | 27017 | `MONGODB_URI` |
| Redis | `redis` | 6379 | `REDIS_HOST`, `REDIS_PORT`, `REDIS_URL` |

Brig creates initial credentials per project and preserves them. PostgreSQL,
MySQL, and MariaDB have an initial database named `brig`; MongoDB uses
authentication in `admin` and a URI targeting `brig`. Redis does not require a
password in this configuration and does not publish ports on the host.

Configure your application to use these variables. Brig does not modify its
`.env` file. PHP receives PDO MySQL for MySQL/MariaDB and PDO PostgreSQL for
PostgreSQL. PHP extensions for MongoDB and Redis are not installed automatically.

## Update a profile used by a project

```bash
brig profile edit python-dev
brig down --project my-api
brig project update my-api
brig run my-api
```

Editing a profile creates another revision. The project keeps its previous
revision until you run `project update`, which adopts the latest revision of its
profile. The next execution generates the corresponding configuration.

Changing a service's major version when it has persistent data requires a data
migration. Brig detects this through volume labels and rejects automatic reuse.
It does not migrate or reinitialize that data.

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

## Stop or delete a definition

```bash
brig down --project my-api
brig project delete my-api
```

`down` removes containers, the network, and attachment copies while preserving
volumes and permanent context. Deleting a
project removes its Brig registration but keeps its folder, profile, runtime
artifacts, and volumes. The deletion check queries Docker, including services
left running after a failed startup.

A profile can only be deleted when no projects reference it:

```bash
brig profile delete python-dev
```

Both deletion confirmations default to **Cancel**. `--yes` skips confirmation for
scripts but retains validation.
