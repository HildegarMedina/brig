# brig

A navigable terminal prototype for profile-based development environments.

**Demo mode:** environment actions are simulations. Brig does not create Docker
containers, launch agents, or request credentials. Dockerfiles can be previewed
or explicitly exported to a new file.
Profile creation and editing query live version sources. New installations
start with empty profile and project lists. Published versions do not guarantee compatibility
between every runtime, package manager, and service combination.

## Install with uv

Requires Linux, Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/).

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

## Walk through the demo

1. Run `brig` in an interactive terminal.
2. Open **Profiles → Create profile**. Choose runtimes, versions, tools, optional
   services, and Claude Code. Review the configuration, then select **Save**.
3. Open **Projects → Create project**. Choose an existing local folder and profile.
4. Open the project and select **Start**, then **Run agent** or **Shell**.
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
brig run claude --project website
brig shell --project website
brig down --project website
```

Inside a registered project folder or a subfolder, omit `--project`:

```bash
brig up
brig run                 # uses the profile's default agent
brig run claude
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
revisions are kept. Stop a running project first with `brig down --project <name>`.
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
project, HTTP serving, database/cache containers, MongoDB/Redis PHP extensions,
and agents require subsequent orchestration work. Brig does not build or start
the image yet. Exact version tags pin the selected runtime/tool releases;
image digests and Debian package versions are not locked.

A **profile** defines runtimes, tools, services, and a default agent. Each edit
creates a revision. A **project** references a profile and stores an independent
snapshot of its selected revision. Updates are explicit and require a stopped
project.

Every project has a unique planned development container, network, agent-data
volume, and service containers and volumes. The eventual Docker implementation
will mount only the project's local folder at `/workspace`. These resource names
are previews, not resources created by the prototype. Container isolation is not
virtual-machine isolation; containers would share the host kernel.

Claude Code is available as a simulation. Codex and OpenCode are listed as future
integrations; attempting to run them explains that status. Real agent adapters,
authentication, Docker orchestration, and `.deb`/`.rpm`
packages are outside this prototype.

## Local data

Definitions and simulated running status persist in
`${XDG_DATA_HOME:-~/.local/share}/brig/state.json`. The first run creates an empty
store. Profiles and projects appear only after you create them.

Use a separate directory to try the demo without affecting your usual data:

```bash
brig --data-dir /tmp/brig-demo
brig --data-dir /tmp/brig-demo project list
```

The store validates its schema and profile/project relationships offline before loading.
Malformed or unsupported data produces an error and is never silently replaced.
Writes use temporary files followed by atomic replacement. New YAML revisions
are prepared before committing state; failed saves remove new documents.
Back up `state.json` and the `profiles` directory before resetting the demo;
move both aside to start with an empty store. Use one brig
session at a time: concurrent writers are not coordinated by this prototype.

## Code structure

- `models`: application records.
- `catalog`: categorized component definitions and agent metadata.
- `versions`: live source adapters and operation-scoped release snapshots.
- `compatibility`: ecosystem-specific runtime range evaluation.
- `profile_yaml`: readable YAML revision documents.
- `dockerfile`: dynamic development image rendering and safe file export.
- `storage`: storage interface, JSON validation, and atomic persistence.
- `engine`: environment interface and simulation implementation.
- `application`: use cases, validation, revision management, and project lookup.
- `presentation`: shared plain text summaries.
- `cli` and `tui`: argument parsing, terminal rendering, and interactive flows.

Application logic depends on storage and execution protocols. The interfaces
share the same use cases; neither performs persistence or execution directly.
Tests cover revision behavior, independent project state, storage failures,
corruption handling, CLI behavior, and wizard confirmation/cancellation.
