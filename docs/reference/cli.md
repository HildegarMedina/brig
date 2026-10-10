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
| `brig profile create` | Wizard to save the first version |
| `brig profile list` | List names and latest versions |
| `brig profile edit NAME` | Wizard that creates another version |
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
| `brig project update NAME` | Adopt the latest profile version when the environment is stopped |
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

Builds a missing image, starts the selected project, and launches its selected
agent inside the development container at `/workspace`. An interactive terminal
is required. Omitting `AGENT` uses the profile's default agent. Only agents in the
project's pinned revision can be launched.

```bash
brig agent codex --project my-api
brig agent opencode --project my-api
```

You can also enter with `brig run my-api` and type `claude`, `codex`, or `opencode`
if selected. Follow the agent's sign-in or provider connection prompts on first
use. Credentials and global configuration persist in an external volume for that
agent, shared across projects under the same Brig data directory and host user.
Signing out affects that agent's shared login. Brig does not copy host credentials
or perform authentication. Conversation directories and conversation databases
use project-specific storage; see [storage](storage.md).

Brig's container launchers enable full tool permissions by default for both
`brig agent` and direct `claude`, `codex`, or `opencode` commands in the shell:

| Agent | Container launcher setting |
| --- | --- |
| Claude Code | `--dangerously-skip-permissions` and inline `skipDangerousModePermissionPrompt: true` settings |
| Codex | `--dangerously-bypass-approvals-and-sandbox` |
| OpenCode | `--auto` and `OPENCODE_PERMISSION='{"*":"allow"}'` |

These settings disable routine tool permission approvals and Claude's initial
bypass-mode acknowledgement. Authentication, provider setup, and questions about
an ambiguous task can still require your input. Restrictions enforced by the
agent itself or an organization still apply. Docker
provides the isolation boundary; agents can change the mounted project files.
The launchers apply settings at runtime without rewriting shared user configs.

See [Claude CLI permissions](https://code.claude.com/docs/en/cli-reference),
[Codex approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security),
and [OpenCode permissions](https://opencode.ai/docs/permissions/).

After updating Brig, run `brig down --project NAME` followed by `brig run NAME`
from the host. The changed Dockerfile selects a new image and regenerates the
launchers. Existing projects do not need a new profile version for this change.

## Terminal interface

`brig profile list` and `brig project list` open a simple list when both input
and output are interactive. Each profile shows its name and latest version;
each project shows its name, status, and profile with its pinned version.
Use Up/Down to select, Enter to view details, and Esc to return or exit.
Selection uses a marker and emphasized text on the terminal's normal background.
The main `brig` menu uses the same lists, with an additional creation option and
the existing profile and project management actions. Redirected output retains
the compact, noninteractive listing.
Profile version numbers continue the existing numbering; stored files keep their
format and require no migration.

Arrow keys navigate; Enter selects; Space toggles multiple selections; Esc goes
back; Ctrl+C exits. Version selectors support searching with `/`. Ctrl+U clears
an input field. The terminal needs at least 45 columns and 12 rows; 90 × 28 or
larger makes details easier to read. Long views scroll with arrow keys.

The interface uses the terminal's default background, highlights the current
selection, and shows the visible range in long menus. Keyboard help wraps onto
two lines on narrow terminals. Set `NO_COLOR=1` to disable colors; basic emphasis
and selection remain available. Non-Unicode locales use ASCII navigation symbols.
Esc waits 100 ms to distinguish it from arrow-key sequences. Set `ESCDELAY` to
another delay in milliseconds if your terminal connection needs more time.

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
