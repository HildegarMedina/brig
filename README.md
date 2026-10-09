# brig

A navigable terminal prototype for profile-based development environments.

**Demo mode:** environment actions are simulations. Brig does not create Docker
containers, launch agents, request credentials, or write into project folders.
The version catalog is static example data, not a list of current releases or a
guarantee of compatibility.

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
authentication, Docker orchestration, a live version catalog, and `.deb`/`.rpm`
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

The store validates its schema and profile/project relationships before loading.
Malformed or unsupported data produces an error and is never silently replaced.
Writes use a temporary file followed by atomic replacement. Back up `state.json`
before resetting the demo; move it aside to seed fresh examples. Use one brig
session at a time: concurrent writers are not coordinated by this prototype.

## Code structure

- `models`: application records.
- `catalog`: demonstration versions and agent metadata.
- `storage`: storage interface, JSON validation, and atomic persistence.
- `engine`: environment interface and simulation implementation.
- `application`: use cases, validation, revision management, and project lookup.
- `presentation`: shared plain text summaries.
- `cli` and `tui`: argument parsing, terminal rendering, and interactive flows.

Application logic depends on storage and execution protocols. The interfaces
share the same use cases; neither performs persistence or execution directly.
Tests cover revision behavior, independent project state, storage failures,
corruption handling, CLI behavior, and wizard confirmation/cancellation.
