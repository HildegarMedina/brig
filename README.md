# Brig

Brig gives each project a Docker development environment with the languages,
tools, databases, and AI coding agents you choose, managed from your terminal.

Projects often need different runtime versions, repeated database setup, and a
place where an agent can work without accessing your whole machine. Brig was
built to make that setup reusable: describe it once in a versioned YAML profile,
use it across projects, and keep each project's environment separate.

You can combine PHP, Python, and Node.js; add package managers, Playwright,
PostgreSQL, MySQL, MariaDB, MongoDB, or Redis; and work with Claude Code, Codex,
or OpenCode. The interface is available in English, Spanish, and Portuguese.

## Tutorial: from an empty folder to an agent-assisted project

### 1. Install Brig

You need Linux, Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/).
Download or clone this repository, then run from its folder as your regular user:

```bash
./scripts/install.sh
brig --help
```

The installer checks Docker Engine, Docker Compose, and your access to Docker.
It installs missing Docker dependencies on supported Debian and Ubuntu hosts.
If it adds your user to the Docker group, log out and back in before continuing.
Other Linux distributions need Docker and Compose installed manually.

If `brig` is not found, run `uv tool update-shell` and open another terminal.
Re-run `./scripts/install.sh` after updating the repository.
[Installation details](docs/tutorials/first-project.md#1-prepare-your-machine).

### 2. Choose your language and create a profile

```bash
brig language en
brig profile create
```

Use `es` for Spanish or `pt` for Portuguese. Name the profile `python-dev`,
choose Python and one of the available versions, then select Codex as your agent.
You can add tools such as uv, a database such as PostgreSQL, or other agents.
Choose a default agent and save.

Use arrows to navigate, Space to select components, Enter to continue, and Esc
to go back. Versions are fetched when you choose components and your selections
are saved as profile **version 1**. Nothing updates automatically.

Playwright is optional. If you select it without Node.js, Brig explains the
requirement and asks you to choose the Node.js version it will also install.

### 3. Register your project and open its environment

```bash
mkdir -p ~/projects/my-api
cd ~/projects/my-api
brig project init
brig run my-api
```

In the wizard, name the project `my-api`, keep the current folder, and choose
`python-dev`. You can register an existing application folder in the same way.

Brig builds missing images, starts your services, and opens Bash inside the
project's development container. The first startup downloads images and packages.
Try:

```bash
python --version
pwd
exit
```

Your project is mounted at `/workspace`: edits there also change the files on your
machine. The shell runs as the chosen agent's unprivileged user; shared group
permissions let your host user and the selected agents edit the code.
Git, curl, jq, and ripgrep are included; selected databases also get CLI clients.
You install application dependencies and start your application yourself.
Publishing application ports requires manual setup.

`exit` returns to your host; the environment keeps running. Inside a registered
folder, `brig run` works without specifying its name.

### 4. Sign in and open a coding agent

From your host:

```bash
brig auth login codex --project my-api
brig agent codex --project my-api
```

Follow the login instructions. If you prefer an API key, use the hidden prompt:

```bash
brig auth set-key codex --project my-api
```

Use `claude` or `opencode` for another agent selected in your profile.
With several agents, `brig run my-api` and `brig agent --project my-api` ask which
to use before entering. Use `brig run my-api --agent codex` to choose explicitly. OpenCode's login command
selects OpenAI; other supported providers use `set-key --provider PROVIDER`.
See [protected credentials](docs/how-to/credentials.md) for the provider list.

All selected agents are installed in the same project container alongside its
languages and tools. Each session runs as its chosen agent's Linux user, with
private project-specific settings and history. Login is reused across projects
for the same agent, host user, and Brig data directory. Separate proxies hold
real provider credentials; the project receives inert placeholders. Network
rules block an agent from connecting directly to another agent's proxy.

Agents run commands without tool approval prompts. They share your project folder
and can modify or delete its files, read secrets stored there, and use the project's
databases. Provider credential protection does not protect secrets in your code.
[Isolation and upgrade details](docs/how-to/agent-isolation.md).

### 5. Give your agent an image or document

Open another host terminal and attach a local file:

```bash
brig project attach my-api ~/Downloads/design.png
```

Brig copies it into the project and prints a `/workspace/.brig/context/attachments/…`
path. Give that path to your agent: “Use this image as the design reference.”
You can attach several files without restarting the environment.

```bash
brig project detach my-api
```

This removes attachment copies and preserves the original files. Stopping the
project also clears those copies. [More about project context](docs/how-to/projects.md#share-images-and-context-with-an-agent).

### 6. Reuse and evolve your environment

Create a second profile based on the first:

```bash
brig profile create --base python-dev --base-version 1
```

Name it `python-web`. Inherited components are already included; the wizard offers
components you can add. The base version stays fixed, and Brig prevents deleting
profiles referenced by projects or inherited profiles.

To change your original profile and apply its latest version to the project:

```bash
brig profile edit python-dev
brig down --project my-api
brig project update my-api
brig run my-api
```

To remove unused images from previous configurations manually:

```bash
brig project clean my-api
```

Cleanup keeps the images for the project's current configuration and any image
used by a running or stopped container. It removes only old Brig development and
credential proxy image tags for this project, including legacy agent images. Source files, volumes, database
images, and build cache are kept. The result reports removed tags; shared Docker
layers mean this count does not represent a fixed amount of reclaimed space.

Editing saves a new profile version; existing projects keep their saved version
until you update them. To explicitly update a child's inherited base, use
`brig profile edit python-web --update-base`.

To share profiles, copy their saved YAML folders from
`${XDG_DATA_HOME:-~/.local/share}/brig/profiles/`, including base profiles and
version histories. On the receiving machine:

```bash
brig profile import ./shared-profiles/
```

Import works offline and preserves versions and inheritance.
[Sharing details](docs/how-to/import-profiles.md).

### 7. Manage your projects from the terminal

```bash
brig
```

The dashboard has Projects, Profiles, and Settings. Use Tab or Left/Right to
switch tabs, Up/Down to select, Enter for actions, and Esc to go back or exit.
You can also work directly with commands:

| Command | What it does |
| --- | --- |
| `brig project list` | View projects and their status |
| `brig profile list` | View profiles and their latest versions |
| `brig project show my-api` | Inspect its folder, profile version, and Docker resources |
| `brig up --project my-api` | Start the environment in the background |
| `brig down --project my-api` | Remove containers and clear attachments; keep source files, data, and login |
| `brig project dockerfile my-api` | Inspect the generated Dockerfile |
| `brig project delete my-api` | Remove a stopped project's registration; keep its files and volumes |

## Learn more or contribute

See the [documentation index](docs/README.md) for guides, the
[command reference](docs/reference/cli.md) for all options, and
[troubleshooting](docs/how-to/troubleshooting.md) when something fails.

Want to help improve Brig? Read the [contribution guide](CONTRIBUTING.md) for
setup, expectations, and suggested tasks.
