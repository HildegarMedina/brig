"""Shared list selection and details for CLI list commands."""

from brig.application import Application
from brig.ui.listings import list_rows
from brig.ui.presentation import configuration_lines, project_lines
from brig.ui.tui.terminal import Terminal


def choose_list(ui: Terminal, title: str, rows: list[str], selected: int) -> int:
    return ui.choose(
        title, rows, selected, help_text="↑↓ move · enter details · esc exit"
    )


def browse_list(app: Application, ui: Terminal, kind: str) -> None:
    profiles = kind == "profile"
    entries = app.state.profiles if profiles else app.state.projects
    title = "Profiles" if profiles else "Projects"
    if not entries:
        ui.notice(
            title,
            [
                f"No {title.lower()}. Use 'brig {kind} {'create' if profiles else 'init'}'."
            ],
        )
        return
    selected = 0
    while True:
        records = list_rows(app, kind)
        selected = choose_list(ui, title, records, selected)
        entry = entries[selected]
        ui.notice(
            entry.name,
            configuration_lines(entry.latest)
            if profiles
            else project_lines(app, entry),
        )
