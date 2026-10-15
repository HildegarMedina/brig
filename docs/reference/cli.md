# Command reference

## Global options

```text
brig [--data-dir DIRECTORY] [--lang {en,es,pt}] [--verbose] [command]
brig --help
brig --version
```

Without a command, Brig opens the terminal interface. `--data-dir` must appear
before the command and changes the directory for definitions, versions, and
engine artifacts. `--lang` selects the language for this invocation and must also
appear before the command. Interface text, help, summaries, and Brig errors are
translated; command names, options, and identifiers keep their original spelling.

## Language

```text
brig language [en|es|pt|auto]
```

Without an argument, show the active language and its code. With a code, save the
preference for this Brig data directory. `auto` follows the terminal locale unless
`BRIG_LANG` overrides it. Language changes require neither Docker nor internet.
Selection order is `--lang`, `BRIG_LANG`, saved preference, then the first nonempty
`LC_ALL`, `LC_MESSAGES`, or `LANG`. Unsupported locales fall back to English;
unsupported `BRIG_LANG` values are ignored. The CLI restores its translation
context after an invocation. See [language settings](../how-to/languages.md).

## Profiles

| Command | Effect |
| --- | --- |
| `brig profile create [--base PROFILE] [--base-version VERSION]` | Wizard to save the first version, optionally inheriting a base |
| `brig profile import PATH [PATH ...]` | Import YAML files or folders with their histories and bases |
| `brig profile list` | List names and latest versions |
| `brig profile edit NAME [--update-base]` | Wizard that creates another version; optionally use the latest base version |
| `brig profile rename NAME NEW_NAME` | Rename a profile; its projects and child profiles follow it |
| `brig profile delete NAME [--yes]` | Delete an unreferenced profile and its YAML documents |

Creating and editing require an interactive terminal and internet to fetch
selected components. Save confirmations default to **Save**. Deletion confirmations
default to **Cancel**; `--yes` confirms directly.

Profile creation offers an independent profile or an existing base profile and
version. `--base` preselects the base; `--base-version` requires `--base`. The
wizard shows inherited configuration for review and offers only components and
agents not already inherited. Inherited components cannot be deselected or
overridden. Additional tools can use inherited runtimes.

Inheritance pins a saved base version and supports chains. Editing a base never
changes a child automatically. Edit a child with `--update-base` to adopt its
base's latest version, preserving the child's own additions; normal editing
offers an explicit Keep/Update choice if a newer base exists. This saves a new
child version, and existing projects retain their snapshots. Self-inheritance and
cycles are rejected. A base referenced by any saved child version cannot be
deleted, including with `--yes`.

`profile import` is noninteractive and works offline. Relative paths refer to
where you run the command; `~` paths are expanded. Directories are scanned
recursively for `.yaml` and `.yml` files, including uppercase extensions. Each
file represents one version. Brig sorts versions and validates the complete
batch before saving it. Supply base documents explicitly or include them in the
folder; Brig does not fetch or search for missing bases elsewhere.

New profiles require a complete history starting at version 1; existing profiles
can receive their next versions. Identical saved versions are skipped. A changed
configuration at an existing version, a name differing only in case, missing
history, invalid inheritance, or invalid YAML rejects the entire batch. Names
and version numbers are preserved; accepted legacy names follow the storage
rules rather than the new-name wizard restrictions. The result reports imported
and already-present versions. Projects keep their snapshots.
See [import profiles](../how-to/import-profiles.md) for examples and file limits.

## Projects

| Command | Effect |
| --- | --- |
| `brig project init` | Register an existing folder with a name and profile |
| `brig project list` | List projects and query their Docker status |
| `brig project show NAME` | Show snapshot, folder, and environment resources |
| `brig project clean NAME` | Remove unused old project image tags; keep current images and data |
| `brig project update NAME` | Adopt the latest profile version when the environment is stopped |
| `brig project rename NAME NEW_NAME` | Rename a project; its Docker environment is kept |
| `brig project delete NAME [--yes]` | Stop the project and remove its containers, legacy project images, volumes, and registration; keep its folder and profile |
| `brig project dockerfile [NAME] [--output FILE]` | Display or export its Dockerfile |
| `brig project attach NAME FILE [FILE ...]` | Copy local files into project context and print their container paths |
| `brig project detach NAME` | Remove all attachment copies for the project; preserve originals |

`project clean` requires Docker and works with running or stopped projects. It
keeps the development and credential proxy images for the current configuration,
and any image used by a running or stopped container. It removes only old image
tags from the shared Brig image repository and legacy tags belonging to that
project, without forcing deletion. Deleting a project keeps shared images. Volumes, source files, database images, generated configuration files,
and build cache are preserved. The result reports removed tags rather than
reclaimed bytes because image layers can be shared.

`project init` is interactive. New profile and project names must contain 1–64
ASCII characters in `kebab-case`: start with a lowercase letter and use lowercase
letters, numbers, and single hyphens between words. Existing records with names
such as `laravel_project` remain accessible; their names are not migrated
automatically. Existing profiles can still be edited without renaming them.

Dockerfile export does not query Docker or version providers and never overwrites
an existing file. Without a name, it resolves the current folder.

Attach files from the host:

```text
brig attach FILE [FILE ...] [--project NAME]
brig project attach NAME FILE [FILE ...]
```

`brig attach` detects the project containing the current folder, including
subfolders; nested registrations select the nearest project. `--project NAME`
overrides detection and works outside registered folders. Without either a
containing project or `--project`, the command reports an error. All positional
arguments are file paths; the existing `project attach NAME` form remains valid.

`attach` accepts regular files, including images and documents. Relative paths
refer to your current directory. It works before startup and while an agent is running, without Docker,
internet, or a container restart. Each file receives a unique directory, so
repeated filenames do not overwrite earlier attachments. Output is one container
path per file. Give that path to the agent; Brig does not inject a chat message.

Remove attachment copies from the host:

```text
brig detach [--project NAME]
brig dettach [--project NAME]
brig project detach NAME
```

`detach` and its `dettach` alias use the same current-folder detection and
`--project` override as `attach`. Without a resolved project they report an error
and leave existing attachments intact. They work offline without restarting the
environment and keep originals, permanent context, and project references.

`detach` removes the reserved `.brig/context/attachments/` directory. A successful
`brig down` also removes those copies. Leaving a shell or agent keeps them until
`detach` or `down`; exiting the CLI or an unexpected shutdown does not expire
them. Permanent context stored elsewhere in `.brig/context/` stays intact.
Removing a copy does not erase content already read or saved by an agent.

## Read-only reference projects

```text
brig reference add PATH [--as ALIAS] [--project NAME]
brig reference list [--project NAME]
brig reference remove ALIAS [--project NAME]
brig reference apply [--project NAME]
```

Without `--project`, Brig detects the project containing the current folder.
`add` links a directory to `/references/ALIAS` without copying it; the alias
otherwise uses the resolved folder name. `list` shows saved configuration,
including host paths. `remove` unlinks configuration and keeps the original files.
These commands do not require Docker or interrupt existing sessions.

Changes apply on the next start of a stopped environment. When it is already
running, close its sessions and use `apply` to recreate only the work container
without restarting database services. `apply` ends sessions inside that container
and requires a running environment. Interactive `run` offers to apply pending
references and enter, warning that other work-container sessions will close.
The default is No; declining or cancelling leaves the environment intact and
ends the invocation. Bash, shell, and agent entry use the same confirmation.
`up`, `--no-input`, and non-interactive entry report pending mount changes without
restarting the running container. A failed apply does not launch the agent.
References persist across `down`. Every agent receives instructions describing
mounted legacy resources. See [project references](../how-to/projects.md#consult-another-project-without-copying-it).

## Run a project

```text
brig run [PROJECT|claude|codex|opencode] [--project NAME] [--agent AGENT]
brig bash [PROJECT] [--agent AGENT]
brig up [PROJECT]
brig down [PROJECT]
brig update [PROJECT] [--yes]
```

All these commands also accept `--project NAME` and `--no-input`.

| Command | Result |
| --- | --- |
| `run` | Build if missing, start, and open the default agent |
| `run --agent AGENT` | Open the requested agent selected in the profile |
| `bash` | Build if missing, start, and open Bash |
| `up` | Start the environment in the background |
| `down` | Remove containers and networks, preserving persistent volumes |
| `update` | Check agent releases and offer to rebuild their installations |

Without a project name, Brig detects the project containing the current folder.
Outside registered folders, an interactive selector asks which project to open.
Without a terminal, or with `--no-input`, supply a project if folder detection is
not possible. Conflicting positional and `--project` names are rejected.

`brig run codex` selects Codex in the detected or interactively chosen project.
The names `claude`, `codex`, and `opencode` are agent shortcuts for `run`;
use `brig run --project codex` to open a project literally named `codex`.
An agent must be selected in the project's profile. Otherwise `run` uses the
saved default, including profiles with multiple agents.

Before opening a chat, Brig checks whether protected credentials exist. If none
exist, an interactive prompt offers native login or an API key. OpenCode API-key
setup also asks for a provider. Existing logins are reused across projects.
Without interactive input, missing credentials produce an actionable error.
`bash`, `up`, and `down` do not require agent login.

Interactive agent launches check available releases using a host-side cache valid
for one day. Claude follows its stable channel; Codex and OpenCode follow their
stable releases. Newer versions show the installed and available versions and
ask before applying changes. A failed background check does not block launch.
Use `--no-update-check` on `run`, or set `BRIG_NO_UPDATE_CHECK=1`, to skip automatic
checks. `--no-input` also skips automatic checks and authentication prompts.

`brig update` explicitly refreshes the release information. It prepares the project,
compares installed versions, and asks before applying available updates. Use
`--yes` to apply updates without a question. Without a TTY, omit `--yes` to only
report available updates. An update builds a separate image, invalidating the
agent installation stages while reusing unaffected build layers, and verifies
installed versions before selecting the image. Build failures keep the previous
image selected. Successful updates recreate the work container; leave other
active sessions first. Project files, login stores, histories, and database
volumes are retained. Other projects keep their existing image selection.

For compatibility, `brig shell` still opens Bash and `brig agent [AGENT]` still
opens an agent. The latter retains its interactive agent picker when omitted.
Prefer `brig run` and `brig bash` for new commands.

`run`, `bash`, `shell`, and `agent` also retain `--command PROGRAM ARGUMENTS...`
to execute a program instead of opening a chat or Bash. Everything after
`--command` belongs to that program, without shell interpretation. These program
executions do not perform automatic login or update prompts and need no TTY.
Opening an interactive agent or Bash requires a terminal.

```bash
brig run my-api
brig run my-api --agent codex
brig run claude
brig bash my-api
brig bash my-api --command python -m unittest -v
brig update my-api
```

## Authentication

Authentication can also be managed explicitly:

```text
brig auth login AGENT [--project NAME]
brig auth set-key AGENT [--project NAME] [--provider PROVIDER] [--stdin]
```

`login` requires an interactive terminal and runs native authentication in a
trusted helper without the project workspace. OpenCode login selects OpenAI.
`set-key` prompts with hidden input, or reads a key from standard input with
`--stdin`. Provider defaults to Anthropic for Claude and OpenAI otherwise.
Codex supports OpenAI, Claude supports Anthropic, and OpenCode supports the
providers listed in [protected credentials](../how-to/credentials.md).
Any selected agent can be authenticated. Keys are never CLI
arguments. Success recreates that project's proxy and work container; restart other
running projects if switching authentication modes. Login persists across
projects; settings and conversations remain project-specific.

Brig's launchers enable full tool permissions by default for `brig agent` and
commands executed in the project work container:

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
The launchers apply settings at runtime without rewriting user configs.

See [Claude CLI permissions](https://code.claude.com/docs/en/cli-reference),
[Codex approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security),
and [OpenCode permissions](https://opencode.ai/docs/permissions/).

After updating Brig, run `brig down --project NAME` followed by `brig run NAME`
from the host. The changed Dockerfile selects a new image and regenerates the
launchers. Existing projects do not need a new profile version for this change.
The work container reuses each selected agent's runtime home, login, and nested
conversation volume names. Legacy development homes remain unmounted. See
[agent isolation and upgrading](../how-to/agent-isolation.md).

## Terminal interface

`brig` opens a workspace dashboard inspired by Docker Sandboxes, with Projects,
Profiles and Settings tabs. Terminals of at least 88 × 24 show a record
panel and a live selection preview side by side. Smaller terminals use a compact
list. The focused record has an emphasized border; its contents keep the normal
terminal background. Status labels remain readable without color.

Use Left/Right or Tab to switch sections, Up/Down to select, Enter to open actions,
and Esc to exit. Press `c` to create, `r` to refresh, and Page Up/Down to scroll the
detail panel. In Settings, Enter opens the language selector and saves the
selected preference; the dashboard updates immediately. In Projects, `s` starts or stops the selected project, `a` opens its
agent picker, and `o` opens a shell after selecting an agent when several exist. Existing confirmation and wizard flows
handle editing and deletion. Status is refreshed on entry, on `r`, and after actions.

`brig profile list` and `brig project list` open the same dashboard for that
section when both input and output are interactive. These views are read-only:
Enter opens details and Esc exits. Redirected output retains a compact text list.
Profile version numbers continue the existing numbering. New documents use
`versions/version-N.yaml`; older state and YAML documents remain compatible
through the storage layer described in [storage](storage.md).

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
