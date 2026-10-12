# Use separate agent environments

Each selected agent has its own container per project. Its image inherits the
profile's languages, tools, database clients, and user identity, then adds only
that agent. The development container used by `brig run` has the languages and
tools without agent executables or their credential mounts.

## Open an agent

Run these commands from your host:

```bash
brig agent --project my-api
brig agent claude --project my-api
brig agent codex --project my-api
brig agent opencode --project my-api
```

Only agents selected in the project's saved profile version are available. Brig
builds missing images, starts development, the selected agent containers, and
database services, then enters the requested agent at `/workspace`. Agent
containers stay running in the background after the chat exits. `brig down`
stops all containers belonging to that project.

Use a noninteractive command to check an agent installation or run a tool with
that agent's environment:

```bash
brig agent codex --project my-api --command codex --version
brig agent claude --project my-api --command python --version
```

Commands keep the existing full tool permissions. Each agent can work on the
same code and use the profile's database services. Attachments are visible to all
project agents through the existing workspace mount.

## What is separated

Each agent container mounts its own project-specific home and conversation
volumes, plus a read-only public authentication view. Real logins are mounted only
in that agent's separate credential proxy. Other agents and development do not
mount either its credential store or private certificate authority.

Login remains shared between projects for the same agent, host user, and Brig
data directory. Settings are private to each project's agent home. Authenticate
from the host using [protected credentials](credentials.md).

The project directory remains writable and shared. Agents can read `.env`, modify
or delete project files, and use project database credentials. The proxy protects
managed provider credentials; it does not hide secrets you put in the workspace
or restrict general internet access. Containers share the host kernel.

## Upgrade existing projects

Update your Brig installation, leave any open shells or chats, and run:

```bash
brig down --project my-api
brig agent --project my-api
```

This regenerates Compose, builds the new targets, and recreates the project's
containers. It requires no profile edit or new profile version. Existing login
volumes and nested conversation-directory volumes keep their names and are
reused. Source files, database volumes, and the old development home are retained.

Each new agent home starts separately. Previous `brig-ID-AGENT-home` volumes
are also retained but not mounted, because they may contain cached credentials. Files that earlier versions stored
elsewhere in the development home, including local SQLite conversation databases
and logs, remain in `brig-ID-home`; they are not automatically copied to the new
`brig-ID-AGENT-runtime-home` volumes. Preserve that legacy volume if you need those files.
Restore only the relevant agent's local state into its own home, with agents
stopped; do not copy the whole development home into every agent container.

`brig project show my-api` shows the planned agent container and volume names.
See [storage](../reference/storage.md) for exact locations.
