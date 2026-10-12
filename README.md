# Brig

Brig runs your projects in isolated Docker development environments from the
command line. Choose your languages, tools, databases, and coding agents in a
reusable profile, then attach that profile to a local project folder.

It supports PHP, Python, and Node.js, plus PostgreSQL, MySQL, MariaDB, MongoDB,
and Redis. Claude Code, Codex, and OpenCode are available agents.

## How it works

- **Profile:** a readable YAML definition of your environment. Available versions
  are fetched when you choose components; your selections are saved as a version.
  Profiles can inherit a fixed version of another profile and add components.
- **Project:** a local folder with a snapshot of a profile version. Editing the
  profile does not automatically change existing projects.
- **Run:** Brig generates the Docker configuration, builds a missing image, starts
  the selected services, and opens a terminal inside the project's container.

Your folder is mounted at `/workspace`, so code changes appear on your machine.
The terminal runs as an unprivileged user with your UID/GID. Each project has its
own containers, network, and data volumes.

Git, Bash, curl, jq, and ripgrep are included. Selecting a database also installs
its command-line client in the development environment.
Playwright is an optional tool for Chromium browser automation, also available
with Python or PHP profiles. When Node.js is missing, its option explains that
Node.js will also be installed. Selecting Playwright adds Node.js to the profile
and asks you to choose its version.

## Install

Requires Linux, Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/). Running
environments also requires Docker Engine and the Docker Compose v2 plugin or
newer, accessible as your regular user. The installer checks these dependencies
and automatically installs missing packages on supported Debian and Ubuntu hosts.

From this repository:

```bash
./scripts/install.sh
brig --help
```

If the command is not found, run `uv tool update-shell` and open another terminal.
After updating the code, run `./scripts/install.sh` again. Run it as your regular
user; system changes use `sudo`. If Docker access is newly configured, log out and
back in before starting projects. Existing working Docker installations are reused.
See [installation details](docs/tutorials/first-project.md#1-prepare-your-machine).

## Start from zero

### 1. Create a profile

```bash
brig profile create
```

For example, name it `python-dev`, select Python and an available version, choose
any tools or databases you need, select your agents and a default agent, and save. Tools and
databases are optional. Use Space to select components and Enter to continue.
Names use `kebab-case`, such as `python-dev` or `my-project`.

### 2. Register a project folder

```bash
mkdir -p ~/projects/my-project
cd ~/projects/my-project
brig project init
```

Name the project `my-project`, keep the current folder, select `python-dev`, and
save. You can also register an existing application folder. This step registers
the folder and its environment; create or install your application inside it.

### 3. Enter the environment

```bash
brig run my-project
```

Brig builds the image if needed and starts the containers automatically. The first
startup downloads the required images and packages. Inside the terminal, you can
run `python --version` and work on your application. From the host, open a
selected agent with `brig agent --project my-project`. Follow its sign-in prompts
the first time.

Each selected agent's login and global configuration persist across projects for
the same host user and Brig data directory. Conversation files are stored per project.
New projects reuse the login; you do not need to sign in for each one.

Each selected agent runs in its own container, with the profile's languages and
tools, its own home, and only its own login/configuration volumes. The development
container has no agent executables or credential mounts. All share the project
folder and can access the project's database services.

Agents run with full tool permissions inside their own containers. They can edit files and run commands without
permission approvals. Docker provides the isolation boundary; edits to the
mounted project folder are reflected on the host.

Type `exit` in Bash to return to your machine. The environment keeps running.
From the host, you can open the default agent or another selected agent:

```bash
brig agent --project my-project
brig agent codex --project my-project
brig agent opencode --project my-project
```

### 4. Everyday commands

| Command | Result |
| --- | --- |
| `brig run my-project` | Prepare the environment and enter its terminal |
| `brig agent --project my-project` | Prepare the environment and open its default agent |
| `brig up --project my-project` | Start in the background |
| `brig down --project my-project` | Stop and remove containers; keep code, data, and login |
| `brig project list` | List registered projects and their status |

Inside a registered folder, `brig run` selects that project automatically. Run
`brig` without arguments to use the interactive menu.

Brig currently prepares the environment. Application dependency installation,
HTTP server startup, and application port publishing require manual setup.

After updating an existing installation, run `brig down --project my-project`
and then `brig agent --project my-project` from the host. Existing login and
conversation-directory volumes are reused. See [agent isolation](docs/how-to/agent-isolation.md)
for the storage changes and security limits.

## Choose your language

Brig's interface and messages are available in English, Spanish, and Portuguese.
Save your preference from Settings in `brig`, or from the command line:

```bash
brig language es
brig language pt
brig language en
```

Use `brig --lang es profile list` for one invocation, or `brig language auto` to
follow your terminal locale. `BRIG_LANG` also selects the language. Commands,
profile names, and YAML keys stay the same in every language.
See [language settings](docs/how-to/languages.md) for the selection order.

## Share and import profiles

Copy saved profile YAML files or their folders to another machine, then import:

```bash
brig profile import ./shared-profiles/
brig profile list
```

Import preserves names, version history, and pinned inheritance. Include the base
profiles and their referenced versions, unless they are already saved locally.
For a new profile, include its history starting at version 1. Identical versions
are skipped; conflicting versions are rejected without changing your profiles.
Existing projects keep their configuration. Import works without Docker or internet.
See [import profiles](docs/how-to/import-profiles.md) for examples.

## Documentation

Start with the [documentation index](docs/README.md).

- [Tutorial: your first project](docs/tutorials/first-project.md).
- [How-to: manage projects](docs/how-to/projects.md).
- [How-to: import profiles](docs/how-to/import-profiles.md).
- [How-to: agent isolation](docs/how-to/agent-isolation.md).
- [How-to: choose your language](docs/how-to/languages.md).
- [Explanation: architecture and execution flow](docs/explanation/architecture.md).
- [Reference: commands](docs/reference/cli.md).
- [Reference: storage and persistence](docs/reference/storage.md).
- [Reference: components and versions](docs/reference/components.md).
- [Troubleshooting](docs/how-to/troubleshooting.md).

Share a local screenshot or document with a project's agent from the host:

```bash
brig project attach my-api ~/Downloads/design.png
```

Give the printed `/workspace/.brig/context/attachments/…` path to the agent.
Copies are available without restarting the container. Remove them with
`brig project detach my-api`; `brig down --project my-api` also cleans attachments.
Original files are preserved. See [project context](docs/how-to/projects.md#share-images-and-context-with-an-agent).
