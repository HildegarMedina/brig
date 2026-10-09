# brig

A terminal application for profile-based, isolated development environments.

`brig run <project>` prepares one project's pinned Dockerfile and Compose
configuration, builds its development image if missing, starts its containers,
and opens an unprivileged Bash terminal at `/workspace`. Only that project's
registered folder is bind-mounted. Services have project-specific networks and
persistent volumes, with no database ports published on the host.

Profile creation and editing query live version sources. New installations
start with empty profile and project lists. Published versions do not guarantee
compatibility between every runtime, package manager, and service combination.
Agent installation and authentication are not implemented yet.

## Install with uv

Requires Linux, Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/).
Starting environments also requires Docker Engine, a running accessible daemon,
and the Docker Compose v2 plugin or newer. Run Brig as your regular user.
Brig reports missing Docker/Compose or socket access errors; it does not install
system software.

```bash
uv tool install .
brig
```

If `brig` is not found, run `uv tool update-shell` and reopen your terminal.
To update an existing installation after changing the code:

```bash
uv tool install --reinstall .
```

## Develop

```bash
uv sync
uv run brig
uv run python -m unittest discover -s tests -v
```

Version constraint evaluation uses `packaging` (Python) and `semantic-version`
(Node.js). Packaging uses setuptools. On distributions that omit `curses` from Python, install your
distribution's Python curses support before opening the interactive interface.

## Create and run a project

1. Run `brig` in an interactive terminal.
2. Open **Profiles → Create profile**. Choose runtimes, versions, tools, optional
   services, and Claude Code. Review the configuration, then select **Save**.
3. Open **Projects → Create project**. Choose an existing local folder and profile.
4. Run `brig run <project_name>` or open the project and select **Shell**.
   Brig builds the image if needed, starts the services, and enters the terminal.
   Type `exit` to return to the host; the environment remains running.
5. Edit the profile to create a new revision. The project retains its snapshot.
6. Stop the project and select **Apply profile update** to adopt the new revision.

Use arrow keys to navigate, Enter to select, Space to toggle selections, Esc to
go back, and Ctrl+C to exit. Version selectors support `/` to search. In text
fields, Ctrl+U clears the field. Resize the terminal to at least 45 columns and
12 rows; 90 × 28 or larger is recommended. Detail views scroll with arrow keys.

## Create a profile

Run `brig profile create`, name the profile, and select components by category:

New profile and project names must use `snake_case`: 1–64 ASCII characters,
starting with a lowercase letter, followed by lowercase letters, digits, or
single underscores between words. Examples: `laravel_project`, `python_api`,
`api_v2`. Spaces, hyphens, uppercase letters, accented letters, and leading,
trailing, or repeated underscores are rejected in the name field. Existing
records remain readable so older installations do not lose access to their data.

| Category | Components |
| --- | --- |
| Runtimes | PHP, Python, Node.js |
| PHP package managers | Composer |
| Python package managers | pip, uv |
| Node.js package managers | npm, pnpm, Yarn Classic |
| Relational databases | PostgreSQL, MySQL, MariaDB |
| Document databases | MongoDB |
| Caches / key-value stores | Redis |

Only package managers for selected runtimes appear. Each chosen component's
versions are fetched when its selector opens, sorted newest first, and searchable
with `/`. There are no version lists to update in the application:

- Runtimes and services use the Linux tags in
  [Docker Official Images](https://github.com/docker-library/official-images).
  These lists cover currently maintained image definitions, not all historical
  releases; moving aliases, image variants, and prereleases are excluded.
- pip and uv use [PyPI's JSON API](https://docs.pypi.org/api/json/), excluding
  empty and fully yanked releases.
- npm, pnpm, and Yarn Classic use the
  [npm registry](https://github.com/npm/registry/blob/main/docs/responses/package-metadata.md),
  excluding deprecated releases. Yarn Modern is not included in this version.
- Composer uses its [official release feed](https://getcomposer.org/versions),
  including the PHP minimum and LTS status for each currently supported release.

Creation and editing require internet access for selected components. A failed
request offers Retry or Cancel; no stale or fabricated fallback is offered.
One wizard keeps a consistent snapshot through review and save; the next wizard
fetches again. Existing profiles, projects, and their pinned versions load
offline. Editing asks for an available replacement if an old version is no
longer listed or compatible with the selected runtime.

### Release channels and compatibility

MySQL versions show **LTS** or **Innovation**, using the official image
repository's [live branch metadata](https://github.com/docker-library/mysql/blob/master/versions.json).
Node.js shows **LTS** or **Current** from the
[official release index](https://nodejs.org/dist/index.json).
New profiles initially highlight the newest listed LTS for Node.js and MySQL.
An existing profile's version remains highlighted when still available.
Composer also shows its published LTS status. Other releases show Stable;
this means a non-prerelease, not an inferred LTS or compatibility guarantee.
If channel metadata does not identify a release, it is marked Channel unverified.

Tools show only releases that satisfy their published runtime requirements:

- npm, pnpm, and Yarn Classic: each release's `engines.node`, evaluated with
  npm range syntax (including `||`, caret, tilde, and patch boundaries).
- pip and uv: the `Requires-Python` constraints of non-yanked distribution
  files, evaluated with Python's version specifiers. For uv, this checks the
  interpreter used to install its Python distribution, not every interpreter
  uv might later manage.
- Composer: the minimum PHP version in the official release feed.

Missing or unreadable constraints are not treated as compatible. If no verified
tool release supports a runtime, an error returns you to runtime/tool selection
while retaining the profile name. Save validates compatibility again, using
the same metadata snapshot. Loading existing revisions remains offline.

This verifies declared runtime requirements. Project dependency resolution,
PHP extensions, operating system and CPU architecture support, and actual
container execution are separate checks for the Docker implementation.

On Save, each profile revision produces a readable YAML document under
`<data-directory>/profiles/profile-<encoded-name>/revision-<number>.yaml`.
The confirmation shows the full path. For example (illustrative pinned versions):

```yaml
schema_version: 1
name: "web_dev"
revision: 1
runtimes:
  php: "8.3.15"
tools:
  composer: "2.8.5"
databases:
  postgresql: "17.2"
caches:
  redis: "7.4.2"
agent: "claude"
```

Versions are strings, never `latest` or floating ranges. Edits create a separate
revision file; existing projects retain their snapshot. YAML files are portable
snapshots for reading and sharing. Importing or applying hand-edited YAML is not
implemented yet; use `brig profile edit` to change a profile. Keep stored revision
files unchanged (edit copies if needed). `state.json` tracks the local history and
projects; neither format is an executable Docker Compose file.

## Commands

```bash
brig --help
brig profile create
brig profile list
brig profile edit web_dev
brig profile delete scratch
brig project init
brig project list
brig project show website
brig project update website
brig project dockerfile website
brig project delete website
brig up --project website
brig run website
brig shell --project website
brig down --project website
```

Inside a registered project folder or a subfolder, omit `--project`:

```bash
brig up
brig run                 # prepare this project and enter its terminal
brig shell               # same terminal flow
brig down
```

The nearest registered parent folder wins if projects are nested. Wizards need
an interactive terminal; list and show commands work in pipelines. Failed
operations return exit code 1, missing interactive terminals return 2, and
Ctrl+C returns 130.

To delete an unused profile, open **Profiles → select profile → Delete profile**
or run `brig profile delete <name>`. The confirmation defaults to **Cancel**;
profile saves default to **Save**. Deleting removes the profile, all revisions,
and their YAML files. A profile referenced by any project (running or stopped)
cannot be deleted; the error lists the projects using it. A deleted name can be
used again for a new profile starting at revision 1.

For scripts, `brig profile delete <name> --yes` explicitly confirms deletion
without an interactive terminal. Project-reference checks still apply. A failed
state save restores the YAML revisions and leaves the profile registered.

To unregister a project, select **Projects → project → Delete project**, or run
`brig project delete <name>`. The confirmation defaults to **Cancel**. Only the
Brig registration is removed: the local folder, code, profile, and profile YAML
revisions are kept. Stop a running project first with `brig down --project <name>`. Docker is
checked even when the saved status says stopped, including services left by a
partially failed startup.
For scripts, `brig project delete <name> --yes` confirms without a terminal;
running-project checks still apply. The name and folder can then be registered
again, and a profile no longer referenced by any project can be deleted.

## Profiles, projects, and agents

### Generate a development Dockerfile

Preview the Dockerfile from the project's pinned profile revision:

```bash
brig project dockerfile laravel_project
```

Inside a registered project folder, omit the name. Export explicitly with:

```bash
brig project dockerfile --output .brig/Dockerfile
```

Existing output files are never overwritten. Generation works offline and does
not change the project's revision or running status. The project detail screen
also offers **View Dockerfile**.

Generation follows the runtime and tool selections in the project's snapshot:

| Runtime | Optional tools |
| --- | --- |
| PHP | Composer |
| Python | pip, uv |
| Node.js | npm, pnpm, Yarn Classic |

One or several runtimes can share the development image. All runtime images
use exact version tags and Debian Bookworm variants. PHP uses the CLI variant
and installs `bcmath`, `intl`, `pcntl`, and `zip`, plus `pdo_mysql` for
MySQL/MariaDB or `pdo_pgsql` for PostgreSQL. Composer is copied from its matching
official image. Selected Python and Node.js tools are installed at their exact
versions. If pip or npm is not selected, the runtime's bundled version remains;
unselected Composer, uv, pnpm, and Yarn are not added.

Mixed profiles keep Python and Node.js under separate `/opt` prefixes to avoid
replacing PHP binaries or libraries. Python shared-library dependencies are
discovered from its selected source image and installed in the final image.
Runtime image definitions live in `RUNTIME_IMAGES` in `dockerfile.py`, with tool
installation and service driver rules kept separately.

The development image runs as the `brig` user in `/workspace`; `BRIG_UID` and
`BRIG_GID` build arguments default to 1000 and can match the project folder's
owner. It keeps the container available with `sleep infinity`. Mounting the
project, HTTP serving, MongoDB/Redis PHP extensions, and agents require subsequent
work. `brig run` and `brig up` build the image if needed and orchestrate its
database/cache containers. Exact version tags pin the selected runtime/tool releases;
image digests and Debian package versions are not locked.

A **profile** defines runtimes, tools, services, and a default agent. Each edit
creates a revision. A **project** references a profile and stores an independent
snapshot of its selected revision. Updates are explicit and require a stopped
project.

Every project has a separate development container, network, home volume,
and selected service containers and data volumes. The local project folder is
mounted at `/workspace`; the Docker socket and other host folders are not
mounted. Container isolation shares the host kernel.

```bash
brig run website                       # build if missing, start, enter Bash
brig up --project website              # start without entering the terminal
brig shell --project website           # prepare and enter the terminal
brig run website --command python --version
brig down --project website            # remove containers/network; keep data
```

`run` without a name discovers the nearest registered parent folder. The terminal
requires a TTY; `--command` runs a program without one and passes its arguments
directly, without shell interpretation. `run` previously referred to simulated
agents; it now runs a project. `brig agent [name] --project <project>` reports
that agent installation is not available yet.

Startup uses the project's saved revision, generates configuration under
`<data-directory>/runtime/brig-<project-id>/<image-hash>/`, and matches the host
user's UID/GID for source-file ownership. The build context includes only the
Dockerfile. Existing development images are reused. Compose starts selected
services and waits for their healthchecks before the development container.
It does not automatically install application dependencies or launch an HTTP
server. No application ports are published in this version.

Database initialization passwords are generated once per project and stored in
`runtime/brig-<project-id>/credentials.json`. Generated files have mode 0600;
credentials are injected using service-specific env files, separate from the
profile YAML. Keep this runtime directory in backups alongside the state and
profiles: missing/corrupt credentials are not replaced over existing volumes.
The developer container receives connection variables (`PGHOST`, `PGPASSWORD`,
`MYSQL_HOST`, `MYSQL_PASSWORD`, `MARIADB_HOST`, `MARIADB_PASSWORD`, `MONGODB_URI`,
`REDIS_HOST`, `REDIS_URL`, etc.). Brig does not modify application `.env` files.

`down` keeps database data and the container home directory in named Docker
volumes. Removing a project's registration also keeps those volumes and the
local runtime artifacts. Major service-version changes require a data migration
before the existing data volume can be reused. Brig refuses automatic major
upgrades rather than reinitializing existing data. Lifecycle operations on the
same project use a local lock. Status displays query Docker; if Docker is
unavailable they show an unknown status instead of assuming the project stopped.

## Local data

Definitions and the last recorded running status persist in
`${XDG_DATA_HOME:-~/.local/share}/brig/state.json`. The first run creates an empty
store. Profiles and projects appear only after you create them.

Use a separate directory to keep definitions and generated configuration apart:

```bash
brig --data-dir /tmp/brig-demo
brig --data-dir /tmp/brig-demo project list
```

The store validates its schema and profile/project relationships offline before loading.
Malformed or unsupported data produces an error and is never silently replaced.
Writes use temporary files followed by atomic replacement. New YAML revisions
are prepared before committing state; failed saves remove new documents.
Back up `state.json`, `profiles`, and `runtime` before resetting local state.
Docker volumes are stored separately by Docker; back up their database data
with the corresponding database tools. Use one brig
session at a time: concurrent writers are not coordinated by this prototype.

## Code structure

- `models`: application records.
- `catalog`: categorized component definitions and agent metadata.
- `versions`: live source adapters and operation-scoped release snapshots.
- `compatibility`: ecosystem-specific runtime range evaluation.
- `profile_yaml`: readable YAML revision documents.
- `dockerfile`: dynamic development image rendering and safe file export.
- `storage`: storage interface, JSON validation, and atomic persistence.
- `compose`: service definitions, connection variables and Compose rendering.
- `engine`: execution protocol and simulation for isolated tests.
- `docker_engine`: real builds, project lifecycle, state inspection and terminal execution.
- `application`: use cases, validation, revision management, and project lookup.
- `presentation`: shared plain text summaries.
- `cli` and `tui`: argument parsing, terminal rendering, and interactive flows.

Application logic depends on storage and execution protocols. The interfaces
share the same use cases; neither performs persistence or execution directly.
Tests cover revision behavior, independent project state, storage failures,
corruption handling, CLI behavior, and wizard confirmation/cancellation.

## Docker integration tests

The default suite runs without Docker; three integration tests are skipped.
To exercise actual builds, per-project isolation, image reuse, Redis persistence,
bind-mount ownership, the five database/cache adapters with PHP connections,
and an interactive terminal through a pseudo-terminal:

```bash
BRIG_DOCKER_TESTS=1 uv run python -m unittest tests.integration.test_lifecycle -v
```

These tests create temporary projects and remove only their own labeled Docker
resources afterward. First execution downloads images and builds them. Pinned
fixture runtime releases can be overridden with `BRIG_TEST_PYTHON`,
`BRIG_TEST_PHP`, and `BRIG_TEST_REDIS`.
