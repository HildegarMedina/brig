"""Read-only card navigation and details for CLI list commands."""

import curses
import os

from brig.application import Application
from brig.errors import Cancelled
from brig.ui.listings import list_records
from brig.ui.presentation import configuration_lines, project_lines
from brig.ui.tui.terminal import Terminal


def choose_card(
    ui: Terminal, title: str, records: list[tuple[str, list[str]]], selected: int
) -> int:
    while True:
        height, width = ui.screen.getmaxyx()
        card_height = max(len(details) for _, details in records) + 3
        capacity = ui._capacity(height)
        if capacity < card_height or width < 45:
            return ui.choose(
                title,
                [f"{name} · {' · '.join(details)}" for name, details in records],
                selected,
            )
        per_page = max(1, capacity // card_height)
        start = selected // per_page * per_page
        rows, styles, border_styles = [], [], []
        card_width = min(68, width - 9)
        colors = getattr(ui, "card_styles", (ui.accent,))
        borders = "┌─┐│└┘"
        if ui._text(borders) != borders or os.environ.get("TERM") == "dumb":
            borders = "+-+|++"
        top, horizontal, right, vertical, bottom, bottom_right = borders
        for index in range(start, min(start + per_page, len(records))):
            name, details = records[index]
            color = colors[index % len(colors)]
            if index == selected:
                color = getattr(ui, "card_selection_style", curses.A_BOLD)
            labels = [name, *details]
            card = [top + horizontal * (card_width - 2) + right]
            for label in labels:
                # Keep each summary to one line; details remain available on Enter.
                label = ui._text(label)
                if len(label) > card_width - 4:
                    label = label[: card_width - 7] + "..."
                card.append(
                    vertical + " " + label.ljust(card_width - 4) + " " + vertical
                )
            card.append(bottom + horizontal * (card_width - 2) + bottom_right)
            rows.extend(card)
            styles.extend([color, *[0] * len(labels), color])
            border_styles.extend([0, *[color] * len(labels), 0])
        ui.render(
            f"{title} · {selected + 1}/{len(records)}",
            rows,
            "↑↓ move · enter details · esc exit",
            row_styles=styles,
            row_border_styles=border_styles,
        )
        key = ui.key()
        if key in ("\x1b", "q"):
            raise Cancelled
        if key in (curses.KEY_UP, "k"):
            selected = (selected - 1) % len(records)
        elif key in (curses.KEY_DOWN, "j"):
            selected = (selected + 1) % len(records)
        elif key in ("\n", "\r", curses.KEY_ENTER):
            return selected


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
        records = list_records(app, kind)
        selected = choose_card(ui, title, records, selected)
        entry = entries[selected]
        ui.notice(
            entry.name,
            configuration_lines(entry.latest)
            if profiles
            else project_lines(app, entry),
        )
