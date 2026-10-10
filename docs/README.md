# Brig documentation

Brig creates a development environment for each project from a profile with
pinned versions. `brig run my-project` prepares that environment and opens a Bash
terminal inside its development container.

## Where to start

| You need to… | Read… |
| --- | --- |
| Create and run your first project | [Your first project](tutorials/first-project.md) |
| Start, stop, update, or delete a definition | [Manage projects](how-to/projects.md) |
| Choose English, Spanish, or Portuguese | [Language settings](how-to/languages.md) |
| Share YAML profiles or import a saved history | [Import profiles](how-to/import-profiles.md) |
| Resolve a Docker, version, or terminal error | [Troubleshooting](how-to/troubleshooting.md) |
| Understand how profiles, projects, and Docker fit together | [Architecture and execution flow](explanation/architecture.md) |
| Look up commands and options | [Command reference](reference/cli.md) |
| Find definitions, credentials, and data | [Storage and persistence](reference/storage.md) |
| Look up components, versions, and compatibility | [Components and versions](reference/components.md) |
| Change the code and run tests | [Development and maintenance](development.md) |

## Current scope

The engine generates Dockerfiles and Compose configurations for PHP, Python, and
Node.js, individually or together. It can start PostgreSQL, MySQL, MariaDB,
MongoDB, and Redis according to the profile, build a missing image, and open an
unprivileged terminal. Selected Claude Code, Codex, and OpenCode agents are installed in the development
image and can be launched with `brig agent` or their commands from that terminal. Sign in on first use;
its login and global configuration persist in a shared agent volume on this
machine, while conversation files have a separate volume per project.

The repository installer checks Docker, Compose, and daemon access; on supported
Debian and Ubuntu hosts it installs missing Docker dependencies. Installing
application dependencies, starting HTTP servers, and publishing application ports
are not implemented. Profile YAML files can be shared and imported, including
version histories and pinned base profiles, without Docker or internet.

## Maintaining this documentation

Write documentation in English and keep it as Markdown in the same repository as
the code. The organization follows [Diátaxis](https://diataxis.fr/): tutorials
provide a learning journey, how-to guides address a task, references describe
details, and explanations help readers understand the system.

When a command, format, or engine responsibility changes, update its page in the
same change. Examples must distinguish illustrative versions from versions fetched
live. Document implemented behavior and identify pending features.
