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
volumes, plus that agent's shared login/configuration volume. Codex does not
receive Claude or OpenCode login volumes; the same rule applies to the others.
Development does not receive any of these agent mounts. Agent containers contain
only their respective agent executable, in addition to the shared profile tools.

Login remains shared between projects for the same agent, host user, and Brig
data directory. Signing out or changing global configuration affects that
agent's other projects. Other agents do not directly mount that storage.

The project directory remains writable and shared. Agents can read `.env` and
other files inside it, modify code, and affect one another through shared project
files. They also receive the project's database connection settings. Avoid
placing an agent's provider credentials inside the shared project folder.

An agent can still read its own credentials. Brig does not yet hide provider
tokens behind an external proxy, block internet access, or isolate containers
with separate virtual machines. Docker's normal host boundary remains in use;
separation is not a guarantee against malicious shared project content.

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

Each new agent home starts separately. Files that earlier versions stored
elsewhere in the development home, including local SQLite conversation databases
and logs, remain in `brig-ID-home`; they are not automatically copied to the new
`brig-ID-AGENT-home` volumes. Preserve that legacy volume if you need those files.
Restore only the relevant agent's local state into its own home, with agents
stopped; do not copy the whole development home into every agent container.

`brig project show my-api` shows the planned agent container and volume names.
See [storage](../reference/storage.md) for exact locations.
