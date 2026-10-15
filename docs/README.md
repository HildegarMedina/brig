# Brig documentation

Brig creates a development environment for each project from a profile with
pinned versions. `brig run my-project` prepares that environment and opens its
selected coding agent; `brig bash my-project` opens a Bash terminal.

## Where to start

| You need to… | Read… |
| --- | --- |
| Create and run your first project | [Your first project](tutorials/first-project.md) |
| Install, update, pin, or publish a Brig release | [Release versions](how-to/releases.md) |
| Start, stop, update, or delete a definition | [Manage projects](how-to/projects.md) |
| Understand project history, credential protection, and upgrades | [Agent isolation](how-to/agent-isolation.md) |
| Sign in without exposing provider tokens to agents | [Protected credentials](how-to/credentials.md) |
| Choose English, Spanish, or Portuguese | [Language settings](how-to/languages.md) |
| Share YAML profiles or import a saved history | [Import profiles](how-to/import-profiles.md) |
| Resolve a Docker, version, or terminal error | [Troubleshooting](how-to/troubleshooting.md) |
| Understand how profiles, projects, and Docker fit together | [Architecture and execution flow](explanation/architecture.md) |
| Look up commands and options | [Command reference](reference/cli.md) |
| Find definitions, credentials, and data | [Storage and persistence](reference/storage.md) |
| Look up components, versions, and compatibility | [Components and versions](reference/components.md) |
| Find contribution guidelines and suggested tasks | [Contributing](https://github.com/HildegarMedina/brig/blob/develop/CONTRIBUTING.md) |
| Change the code and run tests | [Development and maintenance](development.md) |

## Current scope

The engine generates Dockerfiles and Compose configurations for PHP, Python,
Node.js, Go, Rust, and Java, individually or together. It can start PostgreSQL, MySQL, MariaDB,
MongoDB, Redis, RabbitMQ, and Kafka according to the profile, build a missing image, and open an
unprivileged terminal. The default Claude Code, Codex, or OpenCode agent is
installed in the same project container and can run directly from its shell or
through `brig agent`. Sign in through `brig auth login` on the host; a separate credential proxy
holds each login in protected storage shared across projects. Settings and
conversation state remain private to each project.

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
