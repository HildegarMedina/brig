"""Argument parsing and command dispatch for the brig executable."""

import argparse
import curses
import sys
from pathlib import Path

from brig import __version__
from brig.application import Application
from brig.engine import DemoEngine
from brig.errors import BrigError
from brig.presentation import project_lines
from brig.storage import JsonStateStore, default_data_directory
from brig.tui import launch


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="brig", description="Profile-based development environments — Demo mode."
    )
    root.add_argument(
        "--version", action="version", version=f"brig {__version__} (demo)"
    )
    root.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_directory(),
        help="override local demo data directory",
    )
    commands = root.add_subparsers(dest="command")
    profiles = commands.add_parser(
        "profile", help="manage reusable environment profiles"
    ).add_subparsers(dest="action", required=True)
    profiles.add_parser("create", help="open the profile creation wizard")
    profiles.add_parser("list", help="list profiles")
    profiles.add_parser("edit", help="create a new profile revision").add_argument(
        "name"
    )
    deletion = profiles.add_parser(
        "delete", help="delete an unused profile and its YAML revisions"
    )
    deletion.add_argument("name")
    deletion.add_argument(
        "--yes",
        action="store_true",
        help="confirm deletion without opening the interactive confirmation",
    )
    projects = commands.add_parser(
        "project", help="manage isolated projects"
    ).add_subparsers(dest="action", required=True)
    projects.add_parser("init", help="register a local folder using a wizard")
    projects.add_parser("list", help="list projects")
    projects.add_parser("show", help="show project configuration").add_argument("name")
    projects.add_parser(
        "update", help="apply the latest profile revision"
    ).add_argument("name")
    project_deletion = projects.add_parser(
        "delete",
        help="unregister a stopped project while keeping its local folder and profile",
    )
    project_deletion.add_argument("name")
    project_deletion.add_argument(
        "--yes",
        action="store_true",
        help="confirm deletion without opening the interactive confirmation",
    )
    for name, description in (
        ("up", "simulate starting a project"),
        ("down", "simulate stopping a project"),
        ("run", "simulate launching an agent inside a project"),
        ("shell", "simulate opening the project shell"),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument(
            "--project",
            metavar="NAME",
            help="select a project instead of detecting its folder",
        )
        if name == "run":
            command.add_argument(
                "agent", nargs="?", help="agent name; defaults to the profile's agent"
            )
    return root


def _interactive_action(args: argparse.Namespace) -> str | None:
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
        if args.action == "delete":
            return app.delete_profile(args.name)
        return (
            "\n".join(
                f"{p.name} · revision {p.latest.number}" for p in app.state.profiles
            )
            or "No profiles. Use 'brig profile create'."
        )
    if args.command == "project":
        if args.action == "delete":
            return app.delete_project(args.name)
        if args.action == "list":
            return (
                "\n".join(
                    f"{p.name} · {p.profile} r{p.configuration.number} · "
                    f"{'running (simulated)' if p.running else 'stopped'}"
                    for p in app.state.projects
                )
                or "No projects. Use 'brig project init'."
            )
        if args.action == "show":
            return "\n".join(project_lines(app, app.project(args.name)))
        return app.update_project(args.name)
    project = app.resolve_project(args.project, Path.cwd())
    if args.command == "up":
        return app.start(project.name)
    if args.command == "down":
        return app.stop(project.name)
    if args.command == "run":
        return app.run_agent(project.name, args.agent or project.configuration.agent)
    return app.shell(project.name)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    action = _interactive_action(args)
    if action and not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(
            "brig: This action needs an interactive terminal. Use 'brig --help' for commands.",
            file=sys.stderr,
        )
        return 2
    try:
        app = Application(JsonStateStore(args.data_dir.expanduser()), DemoEngine())
        if action:
            return (
                0
                if launch(
                    app, args.data_dir.expanduser(), action, getattr(args, "name", None)
                )
                else 1
            )
        else:
            print("brig · Demo mode")
            print(dispatch(app, args))
        return 0
    except BrigError as error:
        print(f"brig: {error}", file=sys.stderr)
        return 1
    except curses.error:
        print(
            "brig: Cannot open terminal interface. Check TERM or use a supported terminal.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
