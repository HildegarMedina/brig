# Development and maintenance

## Prepare the repository

```bash
uv sync
uv run brig --help
uv run brig
```

The package lives in `src/brig` and tests in `tests`. CLI and TUI use the same
`Application` use cases. Component names and categories live in the catalog;
actual release numbers belong to version providers.

You can keep definitions separate from your regular projects:

```bash
uv run brig --data-dir /tmp/brig-development
```

A separate data directory also produces distinct IDs for Docker resources.
Execution is still real; this is not a simulation mode.

## Local checks

```bash
ruff check src tests
ruff format --check src tests
uv run python -m unittest discover -s tests
```

`ruff` must be available in your development environment. The default suite needs
neither Docker nor network access: it uses controlled providers and the simulation
engine as test dependencies. Real engine boundary tests replace subprocess
execution but generate real files in temporary directories.

Tests cover behavior including profile snapshots, storage relationships, save
failures, CLI options, wizard validation, selected installations, and data
preservation when engine operations fail.

## Docker integration tests

```bash
BRIG_DOCKER_TESTS=1 uv run python -m unittest tests.integration.test_lifecycle -v
```

The four enabled tests verify:

- Entering Bash through a real pseudo-terminal and returning to the host.
- Building a missing image, reusing the container, mounting the correct folder,
  writing files with the user's UID, and preserving Redis data. Starting another
  project and verifying that stopping the first does not affect it.
  Checking that Claude executes before and after recreation, its shared storage
  is visible to both projects, and their conversation files remain separate.
- Starting PostgreSQL, MySQL, MariaDB, MongoDB, and Redis with a PHP project;
  checking health, PDO connections, and MongoDB authentication.
- Running Node.js and Claude in a Node-only profile without optional package
  managers, and checking agent storage permissions.

Tests use temporary profiles and folders. Cleanup selects only resources labeled
with their IDs and image tags belonging to those projects. First startups download
images and build the development image. The default suite explicitly skips these
tests; unit tests do not replace these checks.

Shared agent volumes in these tests are scoped to the temporary data directory and
removed during cleanup. Tests never mount the regular Brig login or authenticate
with a live account; shared storage checks use fixture data.

Fixtures pin concrete releases for repeatability. `BRIG_TEST_PYTHON`,
`BRIG_TEST_PHP`, `BRIG_TEST_NODE`, and `BRIG_TEST_REDIS` override runtimes and Redis to test other
versions; fixtures do not feed the production catalog.

## Add a component

### A tool

Declare the component and its runtime in
[`catalog.py`](../src/brig/catalog.py). Add or reuse its version provider and
requirement evaluation in [`versions.py`](../src/brig/versions.py) and
[`compatibility.py`](../src/brig/compatibility.py).

Also add installation to the Dockerfile generator. Being selectable in the catalog
does not automatically install a new tool. Test selection, compatibility, exact
version, absence when unselected, and real execution.

### A runtime

Register it in the catalog, implement image generation, and define how it coexists
with other runtimes. `RUNTIME_IMAGES` in
[`dockerfile.py`](../src/brig/dockerfile.py) groups current templates, but runtime
placement and libraries also require builder logic.

Keep versions out of the static catalog. Include profiles using that runtime alone
and in combinations, with optional tools and shared dependencies verified through
an actual build.

### A service

Declare it in the catalog and configure its image, data, and healthcheck in
[`compose.py`](../src/brig/compose.py). Add initialization and connection variables
to `service_environment`. If it needs a PHP driver, update `DATABASE_DRIVERS` in
the generator.

Check the image's mount point and differences between releases. Data must stay in
a project-specific volume without ports published by default. Add initialization,
connection, persistence, and data compatibility tests before offering the service
in profiles.

### An agent

Add an `AgentIntegration` in [`agents.py`](../src/brig/agents.py) with its command,
build stage, final-image instructions, runtime packages, and configuration path
and environment variable, and optional history subdirectory. An adapter without installation instructions stays
unavailable. The wizard, profile validation, image generator, and launcher use
this registry, so adding an adapter does not require a new CLI command.

Profile revisions store `agents` and a default `agent`. Validate that the default
is selected, preserve project snapshots, and keep old single-agent revisions and
their immutable YAML readable. Verify actual execution and persistence across
projects and container recreation before making a new integration selectable.

## Change the engine

The contract lives in [`engine.py`](../src/brig/engine.py). The real engine lives
in [`docker_engine.py`](../src/brig/docker_engine.py). Separate file generation,
command execution, and coordination in `Application`.

Keep Docker arguments as lists; do not build host shell commands from user names
or paths. Check ownership of existing resources, wait for successful startup before
recording state, and preserve credentials and volumes when an operation fails.

When changing commands or behavior, update the corresponding page linked from
[`docs/README.md`](README.md) together with the code. Keep documentation in English.
Commits follow Conventional Commits. An incompatible CLI change must use `!` or a
`BREAKING CHANGE` footer and explain how to use the new commands.
