# Work with an agent in the project container

Each project has one work container containing the profile's languages, tools,
database clients, and default coding agent. `brig run` opens Bash in that
container; the installed agent is available directly there:

```bash
brig run my-api
codex
```

Use `codex` only when it is the project's default agent. Claude and OpenCode work
in the same way. From the host, `brig agent --project my-api` launches that same
agent in that same container. Application processes, installed dependencies,
`localhost`, and the project home are shared between the shell and agent.

## One active agent

The pinned profile's default `agent` determines which executable and credential
proxy are installed and started. Older profiles may list several `agents`, but
only the default is active. Requests to launch or authenticate another agent are
rejected before Docker runs. To change agents, edit the profile's default, stop
the project, and apply the new profile version with `brig project update NAME`.
Profile edits do not silently change existing project snapshots.

## Project-specific history

Settings, conversation files, local SQLite databases, and logs remain in that
project's persistent home and history volumes. Two projects using Codex share the
login but have different histories. `brig down` stops containers without deleting
these volumes; the history remains available when the project starts again.
Each agent retains its own history if the project's default changes later.

## Protected credentials

Authenticate from the host with [brig auth](credentials.md). Real credentials
are mounted only in the matching credential proxy and temporary trusted login
helper. The work container receives public CA certificates and inert login
placeholders; reading its auth configuration does not reveal real tokens.

Login storage is shared between projects for the same agent, host user, and Brig
data directory. The project connects only to its active agent's proxy. Neither
other agents' login stores nor their proxies are attached. The proxy adds real
credentials only to approved provider requests and refreshes supported tokens.

The agent can use the account through the proxy and consume quota. The project
folder is writable: agents can modify files, read workspace secrets, and access
project databases. Provider credential protection does not protect secrets you
place in source files. Containers share the host kernel.

## Upgrade existing projects

Leave open shells and chats, update Brig (or run the current repository through
`uv run --locked brig`), then recreate the project:

```bash
brig down --project my-api
brig run my-api
```

The work container reuses the default agent's `brig-ID-AGENT-runtime-home` and
existing `brig-ID-AGENT-history` volumes, including additional history folders.
Login volume names also stay unchanged. Former per-agent containers are removed
as Compose orphans. No source files, database data, or history volumes are deleted.
The old `brig-ID-home` development volume is retained for selective recovery;
it is not mounted because it may contain legacy credentials. Do not copy old
authentication files into the work container.

`brig project show my-api` shows the work container and active agent using the
same container name. See [storage](../reference/storage.md) for exact locations.
