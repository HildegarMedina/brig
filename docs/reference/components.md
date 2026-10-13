# Components, versions, and compatibility

## Current catalog

| Category | Components |
| --- | --- |
| Runtimes | PHP, Python, Node.js, Go, Rust, Java (Eclipse Temurin JDK) |
| PHP tools | Composer |
| Python tools | pip, uv |
| Node.js tools | npm, pnpm, Yarn Classic |
| Java build tools | Maven, Gradle |
| Browser automation | Playwright with Chromium (requires Node.js) |
| Relational databases | PostgreSQL, MySQL, MariaDB |
| Document databases | MongoDB |
| Cache and key/value stores | Redis |

Tools for selected runtimes appear, plus Playwright with its Node.js dependency
notice. At least one runtime is required; tools
and services are optional. A profile can select several runtimes and services.

Profiles select an `agents` list and a default `agent` from that list. Existing
versions containing only `agent` select that one agent automatically. Claude Code,
Codex, and OpenCode are supported individually or together. All selected agents
are installed in the project work container. Multiple-agent entry requires a
choice; the profile default does not bypass selection.

Selected agents use their official native installers, without requiring Node.js.
A common Dockerfile stage provides the profile languages and tools. The final
`dev` target adds all selected agents' executables, users, and configuration. The project
shell and agent run in that same container.
Claude uses its stable channel; Codex and OpenCode resolve their latest releases
when the build stage runs. Unlike runtime and tool versions, agent releases are
not pinned in profile YAML. Docker reuses installed binaries with an image or
cached stage. Automatic updates are disabled; rebuilding the installation stage
is necessary to fetch another release.

See [Claude installation](https://code.claude.com/docs/en/setup),
[Codex CLI](https://learn.chatgpt.com/docs/codex/cli), and
[OpenCode installation](https://opencode.ai/docs/).

## Version sources

Versions are not hardcoded in the catalog. They are fetched when a selector opens
and sorted newest first.

| Components | Source |
| --- | --- |
| Runtimes and services | [Docker Official Images manifests](https://github.com/docker-library/official-images) for Linux images |
| pip and uv | [PyPI JSON API](https://docs.pypi.org/api/json/) |
| npm, pnpm, Yarn Classic, and Playwright | [npm registry](https://github.com/npm/registry/blob/main/docs/responses/package-metadata.md) |
| Composer | [Official release feed](https://getcomposer.org/versions) |
| Maven and Gradle | Docker Official Images manifests |
| Java LTS status | [Adoptium release information](https://api.adoptium.net/v3/info/available_releases) |

Go and Rust list only releases that publish a Debian Bookworm image. Java is
selected by major version (for example `21`); the image provides the latest
Temurin JDK update of that major when it is built. Cargo and rustc come with
Rust, and the Go toolchain includes its module tooling.

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

Java shows **LTS** for the majors Adoptium lists as long-term support.

New profiles initially highlight the newest listed LTS for Node.js, MySQL, and
Java.
Editing preserves the existing selection when it is still valid. Composer shows
the LTS status published in its own feed.

For other components, **Stable** means a non-prerelease; it does not imply LTS
support. When metadata does not identify the channel, it is shown as unverified.

## Tool requirements

Before displaying a tool's versions, Brig filters its requirements against the
selected runtime:

| Tool | Evaluated requirement |
| --- | --- |
| npm, pnpm, Yarn Classic, Playwright | `engines.node`, including npm ranges with `||`, caret, and tilde |
| pip, uv | `Requires-Python` from non-yanked distribution files |
| Composer | Minimum PHP version declared in the release feed |
| Maven, Gradle | Java majors the release's official image is published for |

For uv, this check concerns the Python interpreter used to install its
distribution, not every interpreter uv may later manage. Missing or unreadable
requirements are not treated as compatible.

Saving validates again with the same wizard metadata. If no verified version is
compatible, the wizard returns to selection while preserving the profile name.

This does not validate application dependencies, additional extensions, CPU
architecture, or database migrations. Those checks belong to builds and the
specific project.

## Translation into a Docker environment

Every development image includes Git, Bash, curl, jq, ripgrep, unzip, and tools
agents use to explore code and diagnose problems: `fd`, `tree`, `less`, `file`,
`diff`, `patch`, `make`, `ps`, `lsof`, `ss`, `nc`, `dig`, `wget`, `zip`, `xz`,
`shellcheck`, and `sqlite3`.
Database clients are added automatically for selected services, regardless of the
application language: `psql` for PostgreSQL, `mysql` and `mariadb` for MySQL/MariaDB,
`mongosh` for MongoDB, and `redis-cli` for Redis. These commands run from the
development terminal and connect over the project's private network.

PostgreSQL, MySQL/MariaDB, and Redis clients use Debian Bookworm packages; the
MySQL command is provided by MariaDB's compatible client. MongoDB's shell uses
MongoDB's signed Debian repository. Client package versions are resolved during
the build and can differ from the pinned server version. For version-sensitive
backup/restore operations, use the matching server's tools in its service
container. Client installation does not add database servers to the development
image.

Runtimes use Bookworm variants at their chosen releases. Selected tools are
installed with exact versions. Bundled pip or npm remains when no version of
those tools is selected.

Go and Rust add `gcc`, `g++`, `libc6-dev`, `make`, and `pkg-config` for cgo
and native crates. Java adds `fontconfig`. Module, crate, and dependency caches
(`~/go`, `~/.cargo`, `~/.m2`, `~/.gradle`) live in each user's persistent home.

Agents reach the internet through their credential proxy. Go and Cargo use its
`HTTPS_PROXY` and CA bundle. The JVM ignores both, so when Java is selected each
agent session gets `JAVA_TOOL_OPTIONS` with the proxy and a truststore that adds
the proxy CA to the JDK's own. Maven reads proxies only from settings, so with
Maven the session also sets `MAVEN_ARGS` to a Brig-generated global settings
file; the agent's `~/.m2/settings.xml` still applies on top of it.

PHP adds `bcmath`, `intl`, `pcntl`, and `zip`. It adds `pdo_mysql` for MySQL or
MariaDB, and `pdo_pgsql` with required dependencies for PostgreSQL. PHP extensions
for MongoDB and Redis are not currently installed.

Compose creates one container per selected service using its concrete version.
The development environment does not install database servers inside its own
container or start applications based on folder contents.

## Profile format

Playwright is always shown under Browser automation, including in Python and PHP
profiles, and is unselected by default in new profiles. Its label explains that
Node.js will also be installed when it is missing. Selecting Playwright adds
Node.js to the profile and asks you to choose its version. Existing runtimes
remain selected. Its versions are fetched from npm
and filtered against the selected Node.js version. The image
installs the exact package, its matching Chromium binaries, and Linux dependencies.
Browsers live under `/opt/brig-playwright/browsers`, outside persistent home
volumes. Run `playwright --help`, `playwright screenshot URL screenshot.png`, or
use `require('playwright')` in Node.js. Local project dependencies take precedence;
keep the profile's browser version aligned with a project's own Playwright version.
This installs the CLI/library; it does not configure a Playwright MCP server.

This example uses illustrative versions; the wizard shows releases available
when you create or edit the profile:

```yaml
schema_version: 2
name: "web-dev"
version: 1
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

Import this YAML with `brig profile import FILE`. For an inherited profile, also
provide its base history unless those versions are already saved locally. See
[import profiles](../how-to/import-profiles.md) for the required fields and limits.

This file is a readable snapshot, not a Docker Compose file. Changes create a
new version without modifying the previous one. Projects retain their snapshots
until explicitly updated.

An inherited version additionally identifies its base:

```yaml
extends:
  profile: "base-python"
  version: 2
```

The remaining sections contain the resolved configuration, including inherited
components and the child's additions. The wizard hides inherited installations
from selection. Existing pinned inherited releases are kept without refetching
them; only new additions are checked against available releases.
