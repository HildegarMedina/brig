"""Argument parsing and command dispatch for the brig executable."""

import argparse
import curses
import os
import sys
from contextlib import suppress
from pathlib import Path

from brig import __version__
from brig.application import Application
from brig.docker.engine import DockerEngine
from brig.errors import BrigError
from brig.i18n import (
    LANGUAGES,
    current_language,
    normalize_language,
    reset_language,
    resolve_language,
    set_language,
    tr,
)
from brig.i18n.preferences import load_language, save_language
from brig.persistence.store import JsonStateStore, default_data_directory
from brig.ui.listings import profile_list, project_list
from brig.ui.presentation import project_lines
from brig.ui.tui import launch


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="brig", description=tr("Isolated, profile-based development environments.")
    )
    root.add_argument(
        "--version",
        action="version",
        version=tr("brig {value0}").format(value0=__version__),
    )
    root.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_directory(),
        help=tr("override local data directory"),
    )
    root.add_argument(
        "--lang",
        choices=tuple(LANGUAGES),
        help=tr("language for this invocation: en, es, pt"),
    )
    commands = root.add_subparsers(dest="command")
    language = commands.add_parser(
        "language", help=tr("show or save the interface language")
    )
    language.add_argument("language", nargs="?", choices=(*LANGUAGES, "auto"))
    profiles = commands.add_parser(
        "profile", help=tr("manage reusable environment profiles")
    ).add_subparsers(dest="action", required=True)
    creation = profiles.add_parser(
        "create", help=tr("open the profile creation wizard")
    )
    creation.add_argument("--base", metavar="PROFILE", help=tr("inherit a profile"))
    creation.add_argument(
        "--base-version", type=int, metavar="VERSION", help=tr("pin a base version")
    )
    profiles.add_parser("list", help=tr("list profiles"))
    importing = profiles.add_parser(
        "import", help=tr("import profile YAML files or folders, including bases")
    )
    importing.add_argument("paths", type=Path, nargs="+", metavar="PATH")
    edition = profiles.add_parser("edit", help=tr("create a new profile version"))
    edition.add_argument("name")
    edition.add_argument(
        "--update-base", action="store_true", help=tr("inherit the latest base version")
    )
    deletion = profiles.add_parser(
        "delete", help=tr("delete an unused profile and its YAML versions")
    )
    deletion.add_argument("name")
    deletion.add_argument(
        "--yes",
        action="store_true",
        help=tr("confirm deletion without opening the interactive confirmation"),
    )
    projects = commands.add_parser(
        "project", help=tr("manage isolated projects")
    ).add_subparsers(dest="action", required=True)
    projects.add_parser("init", help=tr("register a local folder using a wizard"))
    projects.add_parser("list", help=tr("list projects"))
    projects.add_parser("show", help=tr("show project configuration")).add_argument(
        "name"
    )
    attach = projects.add_parser(
        "attach", help=tr("copy local context files and print their container paths")
    )
    attach.add_argument("name", help=tr("registered project name"))
    attach.add_argument("files", type=Path, nargs="+", metavar="FILE")
    projects.add_parser(
        "detach", help=tr("remove the project's attachment copies, keeping originals")
    ).add_argument("name")
    dockerfile = projects.add_parser(
        "dockerfile", help=tr("render the project's development Dockerfile")
    )
    dockerfile.add_argument(
        "name",
        nargs="?",
        help=tr("project name; defaults to the registered project for this folder"),
    )
    dockerfile.add_argument(
        "--output",
        type=Path,
        metavar="FILE",
        help=tr("export to a new file instead of printing; existing files are kept"),
    )
    projects.add_parser(
        "update", help=tr("apply the latest profile version")
    ).add_argument("name")
    project_deletion = projects.add_parser(
        "delete",
        help=tr(
            "unregister a stopped project while keeping its local folder and profile"
        ),
    )
    project_deletion.add_argument("name")
    project_deletion.add_argument(
        "--yes",
        action="store_true",
        help=tr("confirm deletion without opening the interactive confirmation"),
    )
    for name, description in (
        ("up", tr("build if needed and start one project's Docker environment")),
        ("down", tr("stop a project's environment, keeping its data")),
        ("run", tr("prepare one project and enter its isolated terminal")),
        ("shell", tr("prepare the current project and enter its isolated terminal")),
        ("agent", tr("prepare a project and launch its agent")),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument(
            "--project",
            metavar="NAME",
            help=tr("select a project instead of detecting its folder"),
        )
        if name == "run":
            command.add_argument(
                "name",
                nargs="?",
                help=tr("project name; defaults to this folder's project"),
            )
        if name in ("run", "shell", "agent"):
            command.add_argument(
                "--command",
                dest="command_program",
                nargs=argparse.REMAINDER,
                help=tr("execute a program instead of opening an interactive terminal"),
            )
        if name == "agent":
            command.add_argument(
                "agent",
                nargs="?",
                help=tr("agent name; defaults to the profile's agent"),
            )
    return root


def _interactive_action(args: argparse.Namespace) -> str | None:
    if (
        args.command in ("profile", "project")
        and args.action == "list"
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    ):
        return f"{args.command}-list"
    if args.command is None:
        return "home"
    if args.command == "profile" and args.action in ("create", "edit"):
        return f"profile-{args.action}"
    if args.command == "profile" and args.action == "delete" and not args.yes:
        return "profile-delete"
    if args.command == "project" and args.action == "init":
        return "project-create"
    if args.command == "project" and args.action == "delete" and not args.yes:
        return "project-delete"
    return None


def dispatch(app: Application, args: argparse.Namespace) -> str:
    if args.command == "profile":
        if args.action == "import":
            return app.import_profiles(args.paths)
        if args.action == "delete":
            return app.delete_profile(args.name)
        return profile_list(app)
    if args.command == "project":
        if args.action == "attach":
            return app.attach(args.name, args.files)
        if args.action == "detach":
            return app.detach(args.name)
        if args.action == "dockerfile":
            return app.project_dockerfile(args.name, Path.cwd(), args.output)
        if args.action == "delete":
            return app.delete_project(args.name)
        if args.action == "list":
            return project_list(app)
        if args.action == "show":
            return "\n".join(project_lines(app, app.project(args.name)))
        return app.update_project(args.name)
    name = getattr(args, "name", None)
    if name and args.project and name != args.project:
        raise BrigError(
            tr(
                "Choose one project: use its name or --project, not different values for both."
            )
        )
    project = app.resolve_project(name or args.project, Path.cwd())
    if args.command == "up":
        return app.start(project.name)
    if args.command == "down":
        return app.stop(project.name)
    if args.command == "agent":
        if args.command_program == []:
            raise BrigError(
                tr("--command needs a program, e.g. --command python --version.")
            )
        if args.command_program is not None:
            return app.run_agent(
                project.name,
                args.agent or project.configuration.agent,
                args.command_program,
            )
        return app.run_agent(project.name, args.agent or project.configuration.agent)
    if args.command in ("run", "shell") and args.command_program == []:
        raise BrigError(
            tr("--command needs a program, e.g. --command python --version.")
        )
    return app.shell(project.name, args.command_program)


def _main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    action = _interactive_action(args)
    if action and not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(
            tr(
                "brig: This action needs an interactive terminal. Use 'brig --help' for commands."
            ),
            file=sys.stderr,
        )
        return 2
    try:
        if args.command == "language":
            if args.language is not None:
                save_language(args.data_dir.expanduser(), args.language)
                set_language(
                    resolve_language(
                        explicit=args.lang,
                        saved=None if args.language == "auto" else args.language,
                    )
                )
                print(
                    tr("Language preference saved: {language}").format(
                        language=tr("Automatic")
                        if args.language == "auto"
                        else LANGUAGES[args.language]
                    )
                )
            else:
                print(
                    tr("Language: {language} ({code})").format(
                        language=LANGUAGES[current_language()], code=current_language()
                    )
                )
            return 0
        app = Application(
            JsonStateStore(args.data_dir.expanduser()),
            DockerEngine(args.data_dir.expanduser() / "runtime"),
        )
        if action:
            return (
                0
                if launch(
                    app,
                    args.data_dir.expanduser(),
                    action,
                    getattr(args, "name", None),
                    base=getattr(args, "base", None),
                    base_version=getattr(args, "base_version", None),
                    update_base=getattr(args, "update_base", False),
                )
                else 1
            )
        else:
            result = dispatch(app, args)
            if result:
                print(result, end="" if result.endswith("\n") else "\n")
        return 0
    except BrigError as error:
        print(tr("brig: {value0}").format(value0=error), file=sys.stderr)
        return 1
    except curses.error:
        print(
            tr(
                "brig: Cannot open terminal interface. Check TERM or use a supported terminal."
            ),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130


def main(argv: list[str] | None = None) -> int:
    # Select translations before the real parser builds help or reports errors.
    bootstrap = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    bootstrap.add_argument("--data-dir", type=Path, default=default_data_directory())
    bootstrap.add_argument("--lang")
    bootstrap.add_argument("rest", nargs=argparse.REMAINDER)
    initial = argparse.Namespace(data_dir=default_data_directory(), lang=None, rest=[])
    # Let the translated real parser diagnose incomplete global options.
    with suppress(argparse.ArgumentError):
        bootstrap.parse_known_args(argv, namespace=initial)
    token = set_language(resolve_language(initial.lang))
    original_gettext = argparse._
    try:
        saved = (
            None
            if initial.lang or normalize_language(os.environ.get("BRIG_LANG", ""))
            else load_language(initial.data_dir.expanduser())
        )
        set_language(resolve_language(initial.lang, saved))
        # argparse uses gettext for its own headings and diagnostics. Keep this
        # binding scoped to a CLI invocation, restoring it even on SystemExit.
        argparse._ = tr
        return _main(argv)
    except BrigError as error:
        print(tr("brig: {value0}").format(value0=error), file=sys.stderr)
        return 1
    finally:
        argparse._ = original_gettext
        reset_language(token)


if __name__ == "__main__":
    raise SystemExit(main())
