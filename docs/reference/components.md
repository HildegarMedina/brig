# Components, versions, and compatibility

## Current catalog

| Category | Components |
| --- | --- |
| Runtimes | PHP, Python, Node.js |
| PHP tools | Composer |
| Python tools | pip, uv |
| Node.js tools | npm, pnpm, Yarn Classic |
| Relational databases | PostgreSQL, MySQL, MariaDB |
| Document databases | MongoDB |
| Cache and key/value stores | Redis |

Only tools for selected runtimes appear. At least one runtime is required; tools
and services are optional. A profile can select several runtimes and services.

Profiles select an `agents` list and a default `agent` from that list. Existing
revisions containing only `agent` select that one agent automatically. Claude Code
is the first available integration; selecting future integrations is blocked until
their installation adapter is implemented.

Selected Claude Code is installed using Anthropic's native
installer and its stable channel. It works without adding Node.js to a PHP or
Python profile. The installer resolves the agent version when its build stage
runs; unlike runtime and tool versions, that version is not pinned in the profile
YAML. Docker reuses the installed binary when reusing an image or cached stage.
Background updates are disabled so the executable stays with the image.
Codex and OpenCode are listed as future integrations.

See [Anthropic's installation documentation](https://code.claude.com/docs/en/setup).

## Version sources

Versions are not hardcoded in the catalog. They are fetched when a selector opens
and sorted newest first.

| Components | Source |
| --- | --- |
| Runtimes and services | [Docker Official Images manifests](https://github.com/docker-library/official-images) for Linux images |
| pip and uv | [PyPI JSON API](https://docs.pypi.org/api/json/) |
| npm, pnpm, and Yarn Classic | [npm registry](https://github.com/npm/registry/blob/main/docs/responses/package-metadata.md) |
| Composer | [Official release feed](https://getcomposer.org/versions) |

Docker manifests describe currently maintained definitions, not an inventory of
all historical releases. Moving aliases, image variants, and prereleases are
excluded. PyPI excludes empty or fully yanked releases; npm excludes deprecated
releases. Yarn Modern is not part of the current catalog.

One creation or editing operation uses a consistent snapshot of fetched metadata.
The next wizard fetches again. A provider failure offers Retry or Cancel; no
replacement versions are fabricated.

Saved version numbers are concrete strings. Loading profiles and projects and
generating a Dockerfile work offline. Building an image or downloading services
may require internet.

## Release channels

MySQL shows **LTS** or **Innovation** based on branch metadata from its
[official image repository](https://github.com/docker-library/mysql/blob/master/versions.json).
Node.js shows **LTS** or **Current** using the
[official release index](https://nodejs.org/dist/index.json).

New profiles initially highlight the newest listed LTS for Node.js and MySQL.
Editing preserves the existing selection when it is still valid. Composer shows
the LTS status published in its own feed.

For other components, **Stable** means a non-prerelease; it does not imply LTS
support. When metadata does not identify the channel, it is shown as unverified.

## Tool requirements

Before displaying a tool's versions, Brig filters its requirements against the
selected runtime:

| Tool | Evaluated requirement |
| --- | --- |
| npm, pnpm, Yarn Classic | `engines.node`, including npm ranges with `||`, caret, and tilde |
| pip, uv | `Requires-Python` from non-yanked distribution files |
| Composer | Minimum PHP version declared in the release feed |

For uv, this check concerns the Python interpreter used to install its
distribution, not every interpreter uv may later manage. Missing or unreadable
requirements are not treated as compatible.

Saving validates again with the same wizard metadata. If no verified version is
compatible, the wizard returns to selection while preserving the profile name.

This does not validate application dependencies, additional extensions, CPU
architecture, or database migrations. Those checks belong to builds and the
specific project.

## Translation into a Docker environment

Runtimes use Bookworm variants at their chosen releases. Selected tools are
installed with exact versions. Bundled pip or npm remains when no version of
those tools is selected.

PHP adds `bcmath`, `intl`, `pcntl`, and `zip`. It adds `pdo_mysql` for MySQL or
MariaDB, and `pdo_pgsql` with required dependencies for PostgreSQL. PHP extensions
for MongoDB and Redis are not currently installed.

Compose creates one container per selected service using its concrete version.
The development environment does not install database servers inside its own
container or start applications based on folder contents.

## Profile format

This example uses illustrative versions; the wizard shows releases available
when you create or edit the profile:

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
agents:
  - "claude"
agent: "claude"
```

This file is a readable snapshot, not a Docker Compose file. Changes create a
new revision without modifying the previous one. Projects retain their snapshots
until explicitly updated.
