# Development and maintenance

Start with the [contribution guide](https://github.com/HildegarMedina/brig/blob/develop/CONTRIBUTING.md) for the pull request
workflow and suggested tasks. This page covers implementation details.

## Prepare the repository

```bash
./scripts/install_pre_commit.sh
uv run brig --help
uv run brig
```

The package lives in `src/brig` and tests in `tests`. CLI and TUI use the same
`Application` use cases. Component names and categories live in the catalog;
actual release numbers belong to version providers.

## Package responsibilities

| Package/module | Responsibility |
| --- | --- |
| `models.py`, `errors.py`, `engine.py` | Records, errors, and the execution contract |
| `application.py` | Shared use cases and state commits |
| `i18n/` | Translation catalogs, language resolution, and separate interface preferences |
| `ui/` | CLI argument handling and shared text summaries |
| `ui/tui/` | Terminal widgets, profile flows, project flows, and top-level navigation |
| `components/` | Component/agent registries, upstream providers, and compatibility |
| `persistence/` | Shared offline validation, safe YAML reading, JSON/YAML transactions, and file export |
| `profiles/` | Immutable version merging and whole-batch import validation |
| `docker/` | Definition generation, Docker execution, workspace files, credentials, and volumes |

`InteractiveApp` delegates feature flows to `ProfileViews` and `ProjectViews`.
`Terminal` owns curses rendering and input. `DockerEngine` coordinates
`DockerClient`, `DockerWorkspace`, `DatabaseCredentials`, and `DockerVolumes`.
Lifecycle locks cover preparation and start/stop operations. JSON and YAML saves
remain coordinated in `JsonStateStore` so failures preserve the previous state.
The simulation engine lives in `tests/demo_engine.py`.

The `dev` Dockerfile target adds all profile-selected agents to its languages
and tools. Compose starts one work container and a credential proxy per selected agent.
The work container reuses each agent's project home and conversation volumes;
real login stores are mounted only in trusted proxy/helper containers. Shell and
agent execution target the same managed work container. Startup also validates
legacy agent/proxy ownership before removing former containers as orphans.

Profile imports reuse the state codec and inheritance validation. The YAML reader
uses a restricted PyYAML SafeLoader, rejects duplicate keys and aliases, and
limits each document to 1 MiB. The merge operates on a copied state; Application
commits only after the complete candidate passes offline validation. Tests cover
portable history, inherited dependencies, conflicts, idempotency, and rollback
when committing state fails. Import never queries Docker or version providers.

Split modules when they gain independent reasons to change. Review files above
roughly 400 lines and functions above 100 lines; these are review signals, not
hard limits. Dockerfile generation has explicit ordered stages, and Compose
assembly delegates database and agent storage definitions to separate helpers.
Internal Python module paths changed in this reorganization; CLI commands,
stored schema, profile versions, and generated resource names remain compatible.

You can keep definitions separate from your regular projects:

```bash
uv run brig --data-dir /tmp/brig-development
```

A separate data directory also produces distinct IDs for Docker resources.
Execution is still real; this is not a simulation mode.

## Local checks

```bash
uv run --locked pre-commit run --all-files
uv run --locked python scripts/check_coverage.py
```

Run `./scripts/install_pre_commit.sh` once per clone. The script requires `uv`,
installs locked development dependencies, installs the Git hook, and runs all
checks. Every commit runs Ruff with automatic
lint fixes and formatting, then runs all unit tests. If Ruff changes files, review
and stage those changes before retrying the commit.

The coverage check requires 100% line coverage across all of `src/brig`, without
module exclusions. A failing test or coverage below 100% blocks the commit, even
when only documentation changes. Run `uv run --locked python scripts/check_coverage.py` to
check the unit suite and coverage directly.

Unit tests need neither Docker nor external network access: they use controlled providers
and the simulation engine as test dependencies. Real engine boundary tests replace
subprocess execution but generate real files in temporary directories. Docker
integration tests run separately using the command below.

The development hook installer does not change host Docker packages. The separate
`scripts/install.sh` command installs Brig for use and prepares its Docker
dependencies. Installer unit tests use fake system commands, so they never run
APT, start host services, or modify user groups.

Tests cover behavior including profile snapshots, storage relationships, save
failures, CLI options, wizard validation, selected installations, and data
preservation when engine operations fail.

## Translate interface text

Use `tr("English template")` from `brig.i18n` for user-facing strings, before
formatting values. Keep the English template literal, and add the same key to
`src/brig/i18n/catalogs/es.json` and `pt.json`. English uses the source template.
Catalogs ship as package data and are loaded through `importlib.resources`;
translations are cached, and the active language uses a `ContextVar`.

Preserve format fields exactly, including any conversion or width specification.
Translate rendered categories and statuses at the presentation boundary. Keep
command names, YAML keys, release numbers, resource names, profile/project names,
and state enums unchanged. Translate application errors where they are created;
Docker, subprocess, upstream, and system diagnostics remain supplied by their
producer. CLI language selection runs before help parsing and restores both the
language context and argparse's gettext binding on exit.

Catalog tests require every literal template to exist in both catalogs, compare
format fields, and verify translated CLI/TUI behavior. Test that translated
views preserve snapshots and generated YAML/Dockerfiles. Only interface
preferences belong in `preferences.json`; do not add them to environment state.

## Docker integration tests

```bash
BRIG_DOCKER_TESTS=1 uv run python -m unittest tests.integration.test_lifecycle tests.integration.test_agents -v
```

The Docker tests verify:

- Entering Bash through a real pseudo-terminal and returning to the host.
- Building a missing image, reusing the container, mounting the correct folder,
  writing files with the user's UID, and preserving Redis data. Starting another
  project and verifying that stopping the first does not affect it.
  Checking that Claude executes in the project work container before and after recreation, settings and conversation files remain separate between projects.
- Starting PostgreSQL, MySQL, MariaDB, MongoDB, and Redis with a PHP project;
  checking health, PDO connections, and MongoDB authentication.
- Running Node.js, Claude, and Playwright; navigating a local page, clicking a
  button, saving a screenshot, and checking agent storage permissions.

- Executing each selected agent (Claude, Codex, and OpenCode) in its project work container without Node.js; checking protected
  fixture credentials, private conversation state, and persistence after recreation.

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
[`catalog.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/components/catalog.py). Add or reuse its version provider and
requirement evaluation in [`providers.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/components/providers.py) and
[`compatibility.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/components/compatibility.py).

Also add installation to the Dockerfile generator. Being selectable in the catalog
does not automatically install a new tool. Test selection, compatibility, exact
version, absence when unselected, and real execution.

### A runtime

Register it in the catalog, implement image generation, and define how it coexists
with other runtimes. `RUNTIME_IMAGES` in
[`dockerfile.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/docker/dockerfile.py) groups current templates, but runtime
placement and libraries also require builder logic.

Keep versions out of the static catalog. Include profiles using that runtime alone
and in combinations, with optional tools and shared dependencies verified through
an actual build.

### A service

Declare it in the catalog and configure its image, data, healthcheck, and
`service_environment` in [`services.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/docker/services.py). Compose
assembly and version-specific mount conventions live in
[`compose.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/docker/compose.py). If it needs a PHP driver, update `DATABASE_DRIVERS` in
the generator.

Check the image's mount point and differences between releases. Data must stay in
a project-specific volume without ports published by default. Add initialization,
connection, persistence, and data compatibility tests before offering the service
in profiles.

### An agent

Add an `AgentIntegration` in [`agents.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/components/agents.py) with its command,
build stage, final-image instructions, runtime packages, and configuration path
and environment variable, and optional history subdirectory. An adapter without installation instructions stays
unavailable. The wizard, profile validation, image generator, and launcher use
this registry, so adding an adapter does not require a new CLI command.

Profile versions store `agents` and a default `agent`. Validate that the default
is selected, preserve project snapshots, and keep old single-agent versions and
their immutable YAML readable. Verify actual execution and persistence across
projects and container recreation before making a new integration selectable.

## Change the engine

The contract lives in [`engine.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/engine.py). The real engine lives
in [`docker/engine.py`](https://github.com/HildegarMedina/brig/blob/develop/src/brig/docker/engine.py). Separate file generation,
command execution, and coordination in `Application`.

Keep Docker arguments as lists; do not build host shell commands from user names
or paths. Check ownership of existing resources, wait for successful startup before
recording state, and preserve credentials and volumes when an operation fails.

When changing commands or behavior, update the corresponding page linked from
[`docs/README.md`](README.md) together with the code. Keep documentation in English.
Commits follow Conventional Commits. An incompatible CLI change must use `!` or a
`BREAKING CHANGE` footer and explain how to use the new commands.

## Credential proxy validation

`brig.auth_proxy` implements protected credential storage, OAuth refresh, inert
native login views, endpoint binding, and streaming redaction. Docker integration
adds one proxy per agent and host-invoked authentication helpers. The proxy image
uses Python 3.12 and pinned mitmproxy independently of profile runtimes.

The unit suite includes a local TLS proxy test with fixture credentials and a
provider that deliberately echoes them. No real provider secrets are required.
Docker integration tests seed fixture API keys and inspect agent/proxy mounts.
Real native OAuth login and inference require Docker and suitable provider
accounts; unit coverage does not substitute for those end-to-end checks.

## Optional live Codex validation

To validate inference with an existing host login, run:

```bash
BRIG_LIVE_CODEX_TESTS=1 uv run --locked python -m unittest tests.integration.test_live_codex -v
```

This uses the protected Codex login from the default Brig data directory and
consumes account quota. It creates temporary registrations and source folders,
asks Codex to write one fixture file, and verifies placeholder credentials and
project history before and after recreation. It also starts a second project
and checks that the history is absent there. Cleanup removes only the test
projects' resources; the shared real login is preserved. It does not perform a
new interactive browser/device login.

## Documentation website

The Markdown files in `docs/` are also the source of the GitHub Pages website.
MkDocs and Material are pinned in the optional `docs` dependency group and
`uv.lock`; they are not installed with Brig.

Preview the site locally:

```bash
uv run --locked --only-group docs mkdocs serve
```

Build the same output as CI, including checks for broken links and anchors:

```bash
uv run --locked --only-group docs mkdocs build --strict
```

Generated HTML is written to `site/`, which is git-ignored. Edit the existing
Markdown pages and add new ones to `nav` in `mkdocs.yml`. The site uses the two
Brig logos for light/dark mode, keeps code copy buttons, and renders Mermaid
architecture diagrams. Keep the README focused on installation and the first
project; link to the website for the full guides and references.

The `Documentation` workflow builds changes on pull requests and pushes to
`master`, `main`, or `develop`. It deploys only the repository's default branch,
or a manually requested run, to:

<https://hildegarmedina.github.io/brig/>

For the first deployment, a repository administrator must select **Settings →
Pages → Build and deployment → Source: GitHub Actions**. Then push the docs
changes to the default branch or run the workflow manually. Pull requests can
build the site without permission to publish it.
