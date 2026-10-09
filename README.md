# Brig

Brig prepares a Docker development environment for each project from a profile
with pinned versions. It can combine PHP, Python, and Node.js, add selected tools,
and start PostgreSQL, MySQL, MariaDB, MongoDB, and Redis.

```bash
brig run my-project
```

It builds the image if missing, starts the environment, and opens an unprivileged
terminal at `/workspace`, mounting the project's registered folder. Each project
has its own network and volumes. Leaving the terminal keeps the environment running.

## Install

Requires Linux, Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/). Running
environments also requires Docker Engine and the Docker Compose v2 plugin or
newer, accessible as your regular user.

From this repository:

```bash
uv tool install .
brig --help
```

If the command is not found, run `uv tool update-shell` and open another terminal.
After updating the code, run `uv tool install --reinstall .`.

## Create and run a project

```bash
brig profile create
cd /path/to/your/project
brig project init
brig run
```

The wizards fetch available versions when creating or editing a profile. The
project stores a snapshot of the chosen revision; updates are explicit. New names
use `kebab-case`, such as `my-project`.

You can also select a project from any folder:

```bash
brig run my-project
brig up --project my-project
brig run my-project --command python --version
brig down --project my-project
```

`down` removes containers and the network while preserving source files and
volumes. Claude Code is installed in selected project images and uses a shared
login on this machine. Application dependency installation, HTTP server
startup, and application port publishing are not implemented yet.

## Documentation

Start with the [documentation index](docs/README.md).

- [Tutorial: your first project](docs/tutorials/first-project.md).
- [How-to: manage projects](docs/how-to/projects.md).
- [Explanation: architecture and execution flow](docs/explanation/architecture.md).
- [Reference: commands](docs/reference/cli.md).
- [Reference: storage and persistence](docs/reference/storage.md).
- [Reference: components and versions](docs/reference/components.md).
- [Troubleshooting](docs/how-to/troubleshooting.md).

## Development

```bash
uv sync
ruff check src tests
ruff format --check src tests
uv run python -m unittest discover -s tests
```

The default suite does not require Docker. Enable the three real integration tests
with:

```bash
BRIG_DOCKER_TESTS=1 uv run python -m unittest tests.integration.test_lifecycle -v
```

See [development and maintenance](docs/development.md) for the code architecture,
testing, and how to add components.
