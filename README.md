<p align="center">
  <img src="docs/assets/logo-brig.png#gh-light-mode-only" alt="Brig logo" width="480">
  <img src="docs/assets/logo-brig-inverse.png#gh-dark-mode-only" alt="Brig logo" width="480">
</p>

# Brig

A development environment for every project, managed from your terminal.

[Read the documentation](https://hildegarmedina.github.io/brig/)

Choose your languages, tools, databases, and coding agents in a reusable
**profile**. Connect a **project** folder to that profile, and Brig prepares its
Docker environment. Your code stays in its local folder.

Brig supports PHP, Python, Node.js, Go, Rust, and Java, with Claude Code, Codex,
and OpenCode. The interface is available in English, Spanish, and Portuguese.
[See all supported components.](docs/reference/components.md)

## 1. Install Brig

On Linux, run this as your regular user, without `sudo`:

```bash
curl -fsSL https://github.com/HildegarMedina/brig/releases/latest/download/install.sh | bash
```

No repository checkout is needed. The installer prepares the tools Brig needs
and installs missing Docker dependencies on supported Debian and Ubuntu hosts.
Other distributions need Docker Engine and Compose installed beforehand.

Open a new terminal if prompted. If the installer adds you to the Docker group,
log out and back in before continuing.

```bash
brig --version
```

[Installation details and exact versions.](docs/how-to/releases.md)

## 2. Create your first profile

```bash
brig profile create
```

Name it `python-dev`, select Python and an available version, choose Codex as your
agent, and save. You can add tools and databases when your project needs them.

## 3. Connect a project

Use an existing project folder, or create one to try Brig:

```bash
mkdir -p ~/projects/my-api
cd ~/projects/my-api
brig project init
```

Name the project `my-api` and select `python-dev`. Then start it:

```bash
brig run
```

The first run builds the environment and opens Codex. If credentials are missing,
Brig offers authentication before opening the chat. You can also choose Claude
Code or OpenCode when creating your profile.

Your project is available inside the environment at `/workspace`. Changes made
by the agent also change your local files. Install your application's dependencies
and start its processes from there, or open Bash with `brig bash`.

Exit the agent to return to your terminal. The environment keeps running until
you stop it:

```bash
brig down
```

Your source files, database data, and agent history are kept. Run `brig run` to
continue later. [More about projects and authentication.](docs/how-to/projects.md)

## Everyday commands

Inside your project folder:

| Task | Command |
| --- | --- |
| Open the dashboard | `brig` |
| Return to your agent | `brig run` |
| Open Bash | `brig bash` |
| Start the environment without entering | `brig up` |
| Share an image or document with the agent | `brig attach ./design.png` |
| Remove attachment copies, keeping originals | `brig detach` |
| Add a read-only reference project | `brig reference add ../old-api --as legacy` |
| Stop the environment, keeping persistent data | `brig down` |

Attachments print a path you can give to the agent. Reference projects appear
under `/references/ALIAS`; Brig tells the agent they are available. If a new
reference needs the work container recreated, `brig run` offers to apply it.

Outside a project folder, select one explicitly, for example `brig run my-api`.
[See the command reference.](docs/reference/cli.md)

## Keep things up to date

```bash
brig self update    # Update Brig
brig update         # Update this project's coding agents
```

Brig checks for new stable releases once per 24 hours and shows a notice in
interactive terminals. It installs updates only when requested. Use
`brig self pin` to keep the current Brig version, and `brig self unpin` to allow
updates again. [Version management.](docs/how-to/releases.md)

Editing a profile creates a new version. Existing projects keep their saved
configuration until you [apply the profile update](docs/how-to/projects.md).

## Before you work

Agents run commands without tool approval prompts and can modify project files
or read secrets stored there. Provider credentials managed through `brig auth`
stay in separate credential proxies. [Agent isolation.](docs/how-to/agent-isolation.md)

Brig prepares your development environment; publishing application ports requires
manual setup. [Troubleshooting.](docs/how-to/troubleshooting.md)

## Learn more

- [Complete first-project tutorial](docs/tutorials/first-project.md)
- [Documentation](docs/README.md)
- [Contributing](CONTRIBUTING.md)

For development from a checkout, install with `./scripts/install.sh`.
