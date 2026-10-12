# Troubleshooting

## Docker is unavailable

If Docker or Compose is missing, run `./scripts/install.sh` from the repository
as your regular user. It installs missing dependencies on supported Debian and
Ubuntu hosts and checks daemon access. Other distributions require manual Docker
installation; see [installation](../tutorials/first-project.md#1-prepare-your-machine).

If package installation reports a conflict, resolve it using your distribution's
Docker instructions and rerun the installer. It does not remove existing packages
automatically. If it added you to the `docker` group, log out and back in before
starting projects. The Python-only `uv tool install` command does not perform
these host checks.

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
and apply its new version to the stopped project.

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

Agents are installed in their own images. `claude`, `codex`, and `opencode` are
not installed in the development shell opened by `brig run`. Exit that shell and
launch from the host:

```bash
brig agent --project my-api
brig agent codex --project my-api --command codex --version
```

After updating Brig, run `brig down --project my-api` before starting the project
again. Brig rebuilds the required images and recreates containers while retaining
named volumes. Existing login and conversation-directory volumes are reused;
see [agent isolation](agent-isolation.md) for legacy home storage.
Use `brig auth login codex --project my-api` from the host, substituting your
selected agent. Native login inside the agent uses placeholders and cannot
replace the protected login. For API keys, use `brig auth set-key`.
See [protected credentials](credentials.md).

An expired or revoked session may require login again. Restart other running
projects after changing authentication modes. If the credential proxy is unhealthy,
check Docker startup/build errors; it must publish a public certificate and login
view before the agent starts. Unsupported provider endpoints and compressed
credentialed responses are rejected. Do not disable TLS verification or mount the
credential store into the agent to work around these errors.
