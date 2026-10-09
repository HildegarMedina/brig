# Command reference

## Global options

```text
brig [--data-dir DIRECTORY] [command]
brig --help
brig --version
```

Without a command, Brig opens the terminal interface. `--data-dir` must appear
before the command and changes the directory for definitions, revisions, and
engine artifacts.

## Profiles

| Command | Effect |
| --- | --- |
| `brig profile create` | Wizard to save the first revision |
| `brig profile list` | List names and latest revisions |
| `brig profile edit NAME` | Wizard that creates another revision |
| `brig profile delete NAME [--yes]` | Delete an unreferenced profile and its YAML documents |

Creating and editing require an interactive terminal and internet to fetch
selected components. Save confirmations default to **Save**. Deletion confirmations
default to **Cancel**; `--yes` confirms directly.

## Projects

| Command | Effect |
| --- | --- |
| `brig project init` | Register an existing folder with a name and profile |
| `brig project list` | List projects and query their Docker status |
| `brig project show NAME` | Show snapshot, folder, and environment resources |
| `brig project update NAME` | Adopt the latest profile revision when the environment is stopped |
| `brig project delete NAME [--yes]` | Remove a stopped project's registration |
| `brig project dockerfile [NAME] [--output FILE]` | Display or export its Dockerfile |

`project init` is interactive. New profile and project names must contain 1–64
ASCII characters in `kebab-case`: start with a lowercase letter and use lowercase
letters, numbers, and single hyphens between words. Existing records with names
such as `laravel_project` remain accessible; their names are not migrated
automatically. Existing profiles can still be edited without renaming them.

Dockerfile export does not query Docker or version providers and never overwrites
an existing file. Without a name, it resolves the current folder.

## Run a project

```text
brig run [NAME] [--project NAME] [--command PROGRAM ARGUMENTS...]
brig up [--project NAME]
brig shell [--project NAME] [--command PROGRAM ARGUMENTS...]
brig down [--project NAME]
```

| Command | Preparation | Result |
| --- | --- | --- |
| `run` | Build if missing and start | Open Bash or execute `--command` |
| `up` | Build if missing and start | Leave the environment running in the background |
| `shell` | Build if missing and start | Open Bash or execute `--command` |
| `down` | Use the existing managed configuration | Remove containers and network; preserve volumes |

`run NAME` and `--project NAME` select one project. Supplying different names
with both is an error. Without a selection, the current folder must be inside a
registered project.

After `--command`, every option belongs to the program, for example:

```bash
brig run my-api --command python -m unittest -v
```

Opening Bash requires stdin and stdout connected to a terminal. Executing a
program with `--command` does not require a TTY. Brig does not interpret arguments
with a shell; specify one as the program if needed.

## Agents

```text
brig agent [AGENT] [--project NAME]
```

Builds a missing image, starts the selected project, and launches Claude Code
inside its development container at `/workspace`. An interactive terminal is
required. Omitting `AGENT` uses the profile's default agent. Codex and OpenCode
remain future integrations.

You can also enter with `brig run PROJECT` and type `claude`. On first use,
follow Claude's sign-in prompts. Its configuration and credentials stay in the
shared agent volume. Projects registered under the same Brig data directory and
host user reuse that login on this machine. Conversation files under Claude's
`projects/` directory have a separate volume per project. Brig does not copy host
credentials. Signing out of Claude affects the shared login.

Profiles select a list of agents and a default from that list. The command can
only launch agents selected in the project's pinned revision. Claude Code is the
first available integration.

## Terminal interface

Arrow keys navigate; Enter selects; Space toggles multiple selections; Esc goes
back; Ctrl+C exits. Version selectors support searching with `/`. Ctrl+U clears
an input field. The terminal needs at least 45 columns and 12 rows; 90 × 28 or
larger makes details easier to read. Long views scroll with arrow keys.

Validation errors are highlighted in red. **Shell** prepares the project and opens
its terminal; leaving it returns to the menu. **View Dockerfile** displays the
definition without starting Docker.

## Exit statuses

| Code | Meaning |
| --- | --- |
| 0 | Operation completed or wizard closed without an error |
| 1 | Application, Docker, or executed program error |
| 2 | Invalid arguments or missing terminal for a wizard |
| 130 | Interrupted with Ctrl+C |

An executed program's error status appears in Brig's message; the CLI returns 1
for that failed operation, not necessarily the program's status. Leaving Bash
keeps the environment running.
