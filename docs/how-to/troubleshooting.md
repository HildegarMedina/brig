# Troubleshooting

## Docker is unavailable

If Brig reports that Docker is not installed, install Docker Engine and the
Compose plugin according to your distribution's documentation. Brig does not
install system services.

If it cannot connect to the daemon, check:

```bash
docker version
docker compose version
```

The first command must show the server and the second the Compose version. Check
that the daemon is running and your user can access its socket. Run Brig as your
regular user, without `sudo`; the engine needs a nonzero UID/GID to create the
container's unprivileged user.

You can inspect profiles and project configuration without starting an
environment. When Docker is unavailable, the project's status appears as unknown.

## `brig run` requires an interactive terminal

Opening Bash requires a real terminal. For a script, pipeline, or CI task, specify
a program:

```bash
brig run my-api --command python --version
```

Passing `--command` without a program is an error. A program that exits with a
nonzero status produces a Brig error; the environment remains running.

## Brig cannot find the project

Check registered projects:

```bash
brig project list
brig run my-api
```

Without a name, Brig looks for a registered folder containing the current
directory. `project init` registers an existing folder; it does not create that
folder or initialize a framework.

## The first startup fails while downloading or building

Profile versions are pinned, but images or packages may be unavailable for your
architecture or no longer published. Brig does not replace the chosen version
with `latest`.

Read the Docker output. Resolve the network, availability, or architecture issue
and run `brig run my-api` again. If you need another version, edit the profile
and apply its new revision to the stopped project.

## A service never becomes healthy

Compose waits for services before starting the development container. A failure
may leave some containers created or running. Inspect the service logs using the
name shown by `brig project show my-api`, for example:

```bash
docker logs brig-PROJECT_ID-mysql
brig down --project my-api
```

Replace the example name with the actual one. `down` preserves data so you can
investigate or retry startup. Brig does not record a failed startup as successful;
subsequent status queries inspect Docker.

## Credentials are missing or a database's major version changed

Restore `credentials.json` from a backup of the project's runtime directory if
the file is missing or damaged. Do not delete volumes to resolve a credentials
issue: they contain the database's data.

If you changed a major version, return to a compatible profile configuration or
migrate the data using the database's tools before reusing it. Brig does not
implement a migration wizard or a volume deletion option.

## Versions do not appear in the selector

Creating and editing profiles requires internet. A provider failure offers Retry
or Cancel. There are no fabricated version lists as a fallback. Tool versions are
filtered according to their declared requirements for the selected runtime. See
[components and versions](../reference/components.md).

## An agent does not start

Claude Code is installed in the development image. If an older container says
`claude: command not found`, exit its terminal, update Brig, and run
`brig run my-api` again. Brig builds the updated image and recreates the
development container while preserving the source folder and named volumes.

Use `claude --version` inside the container to check installation, or launch it
directly with `brig agent --project my-api`. Follow its sign-in prompts on first
use. Brig does not copy credentials from the host or automate sign-in. Codex and
OpenCode are not implemented yet.

Signing in once shares that session with other projects under the same Brig data
directory and host user. `down`, recreating a container, or deleting a project
registration preserves the shared login. An explicit logout affects all projects
using it; an expired or revoked session may require signing in again.
