# Choose an agent in the project container

A profile can select Codex, Claude, OpenCode, or any combination. Brig installs
all selected agents alongside the profile's languages, tools, and database
clients in one project work container.

## Select before entering

```bash
brig run my-api
brig agent --project my-api
```

With one selected agent, Brig uses it directly. With several, Brig shows their
names and requires a choice before starting Docker or opening the session.
Canceling the picker does not start the project. The saved default does not skip
the choice when several agents are selected.

Choose explicitly to skip the picker:

```bash
brig run my-api --agent codex
brig agent claude --project my-api
brig shell --project my-api --agent opencode
brig run my-api --agent codex --command codex --version
```

Noninteractive commands must name an agent when the profile selects several.
Only selected agents can be launched or authenticated. `brig up` starts the
background environment without opening an agent session and needs no choice.

`run` opens Bash for the chosen agent; `agent` opens its chat. Both use the same
container and `/workspace`, so application processes, localhost, installed system
tools, and project dependencies are shared. To switch agent identities, open a
new session through Brig from the host. A launcher rejects another agent's user.

## Users, history, and shared code

Each selected agent runs as a distinct unprivileged Linux UID, with its own
private home, configuration, conversation files, SQLite state, and logs. Homes
are mounted at `/opt/brig-agent-home/AGENT` and persist in project-specific
`brig-ID-AGENT-runtime-home` volumes. History volumes retain their existing names.
Two projects can share login while keeping their histories separate.

The work container initializes ownership and network rules before becoming
healthy, then drops the initializer's privileges. Agent processes have no
capabilities and cannot gain privileges through setuid programs. They cannot
read the other agents' homes or edit the initializer or firewall rules.

The project folder is shared through the host user's group. Initialization adds
recursive group access ACLs and default directory ACLs without following symbolic
links. Agent sessions use umask 002. Existing files retain their owner; new files
are owned by the creating agent UID and use the host group so the host user and
other agents can edit them. The source filesystem must support POSIX ACLs;
initialization fails instead of silently weakening isolation when it cannot.

## Protected credentials and proxies

Authenticate from the host with [brig auth](credentials.md). Real tokens are
mounted only in the corresponding trusted credential proxy and temporary native
login helper. The work container sees public CA certificates and inert login
placeholders, never private CA keys or real login stores.

Each agent has its own internal proxy network and a separate proxy egress network.
Kernel firewall rules reject connections from an agent UID to other agents'
proxy IPs, including attempts made directly without HTTP_PROXY. IPv4 forwarding
is disabled in the work container. Each session loads its own proxy and CA settings.

This prevents direct cross-proxy access. Agents still share writable code and
application processes, so one can influence code another later executes; it is
not complete isolation of collaborating agents. The host Docker administrator
remains trusted. Workspace secrets and database credentials remain accessible.

Saving authentication recreates the proxy and work container, so leave active
chats before changing login or API-key mode. Login is shared by agent, host user,
and Brig data directory; project history is retained when containers are stopped.

## Upgrade existing projects

Leave shells and chats, update Brig (or use `uv run --locked brig`), then run:

```bash
brig down --project my-api
brig run my-api
```

Existing per-agent runtime homes and history volumes are reused at their new
mount locations and assigned to their agent UID. Former separate agent containers
are retired as Compose orphans. The common work home uses `brig-ID-work-home`;
legacy development homes are retained but not mounted because they may contain
cached credentials. No source files or persistent history/database volumes are
deleted by recreation.

`brig project show my-api` lists every selected agent pointing to the same work
container. See [storage](../reference/storage.md) for exact names.
