# brig

A navigable terminal prototype for profile-based development environments.

**Demo mode:** environment actions are simulations. Brig does not create Docker
containers, launch agents, request credentials, or write into project folders.
Profile creation and editing query live version sources. The seeded sample
profiles remain examples. Published versions do not guarantee compatibility
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

There are no runtime dependencies outside Python's standard library. Packaging
uses setuptools. On distributions that omit `curses` from Python, install your
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

- Runtimes, Composer, and services use the Linux tags in
  [Docker Official Images](https://github.com/docker-library/official-images).
  These lists cover currently maintained image definitions, not all historical
  releases; moving aliases, image variants, and prereleases are excluded.
- pip and uv use [PyPI's JSON API](https://docs.pypi.org/api/json/), excluding
  empty and fully yanked releases.
- npm, pnpm, and Yarn Classic use the
  [npm registry](https://github.com/npm/registry/blob/main/docs/responses/package-metadata.md),
  excluding deprecated releases. Yarn Modern is not included in this version.

Creation and editing require internet access for selected components. A failed
request offers Retry or Cancel; no stale or fabricated fallback is offered.
One wizard keeps a consistent snapshot through review and save; the next wizard
fetches again. Existing profiles, projects, and their pinned versions load
offline. Editing asks for an available replacement if an old version is no
longer listed. Runtime dependencies are checked; detailed package-manager
runtime version compatibility is not yet resolved automatically.

On Save, each profile revision produces a readable YAML document under
`<data-directory>/profiles/profile-<encoded-name>/revision-<number>.yaml`.
The confirmation shows the full path. For example (illustrative pinned versions):

```yaml
schema_version: 1
name: "web-dev"
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
brig profile edit web-dev
brig project init
brig project list
brig project show website
brig project update website
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

## Profiles, projects, and agents

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
`${XDG_DATA_HOME:-~/.local/share}/brig/state.json`. The first run seeds two sample
profiles and projects; sample projects have no local folder mounted.

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
move both aside to seed fresh examples. Use one brig
session at a time: concurrent writers are not coordinated by this prototype.

## Code structure

- `models`: application records.
- `catalog`: categorized component definitions and agent metadata.
- `versions`: live source adapters and operation-scoped release snapshots.
- `profile_yaml`: readable YAML revision documents.
- `storage`: storage interface, JSON validation, and atomic persistence.
- `engine`: environment interface and simulation implementation.
- `application`: use cases, validation, revision management, and project lookup.
- `presentation`: shared plain text summaries.
- `cli` and `tui`: argument parsing, terminal rendering, and interactive flows.

Application logic depends on storage and execution protocols. The interfaces
share the same use cases; neither performs persistence or execution directly.
Tests cover revision behavior, independent project state, storage failures,
corruption handling, CLI behavior, and wizard confirmation/cancellation.
