"""Responsive dashboard composition; drawing does not perform application actions."""

import curses
import os
import textwrap
import unicodedata
from dataclasses import dataclass

from brig.i18n import tr
from brig.ui.tui.terminal import Terminal


@dataclass
class DashboardItem:
    name: str
    status: str
    summary: str
    context: str
    details: list[str]


class DashboardRenderer:
    def __init__(self, ui: Terminal):
        self.ui = ui
        self.styles = {
            "focus": ui.accent,
            "border": curses.A_DIM,
            "running": curses.A_BOLD,
            "stopped": curses.A_BOLD,
            "unknown": ui.error_style,
        }
        if "NO_COLOR" not in os.environ and curses.has_colors():
            try:
                background = -1
                try:
                    curses.use_default_colors()
                except curses.error:
                    background = curses.COLOR_BLACK
                for pair, (name, color) in enumerate(
                    (
                        ("focus", curses.COLOR_MAGENTA),
                        ("running", curses.COLOR_GREEN),
                        ("stopped", curses.COLOR_YELLOW),
                    ),
                    3,
                ):
                    curses.init_pair(pair, color, background)
                    self.styles[name] = curses.color_pair(pair) | curses.A_BOLD
            except curses.error:
                pass

    def write(self, y: int, x: int, text: str, width: int, style: int = 0):
        text = self.ui._text(text)
        text = "".join(char if char.isprintable() else " " for char in text)
        sizes = [
            0
            if unicodedata.combining(char)
            else 2
            if unicodedata.east_asian_width(char) in ("W", "F")
            else 1
            for char in text
        ]
        if sum(sizes) > width:
            used = 0
            end = 0
            for size in sizes:
                if used + size > max(0, width - 3):
                    break
                used += size
                end += 1
            text = text[:end] + "." * min(3, width)
        self.ui._write(y, x, text, style)

    def box(self, y: int, x: int, height: int, width: int, *, focused=False):
        glyphs = "╭─╮│╰╯"
        if self.ui._text(glyphs) != glyphs or os.environ.get("TERM") == "dumb":
            glyphs = "+-+|++"
        top, line, right, side, bottom, corner = glyphs
        style = self.styles["focus" if focused else "border"]
        self.write(y, x, top + line * (width - 2) + right, width, style)
        for row in range(y + 1, y + height - 1):
            self.write(row, x, side, 1, style)
            self.write(row, x + width - 1, side, 1, style)
        self.write(
            y + height - 1, x, bottom + line * (width - 2) + corner, width, style
        )

    def draw(
        self,
        tabs: list[str],
        tab: int,
        items: list[DashboardItem],
        selected: int,
        detail_offset: int,
        footer: str,
        *,
        read_only=False,
    ):
        height, width = self.ui.screen.getmaxyx()
        if width < 88 or height < 24:
            rows = [
                f"{item.name} · {tr(item.status)} · {item.summary}" for item in items
            ]
            self.ui.render(
                tr(tabs[tab]),
                rows
                or [
                    tr("No records yet.")
                    if read_only
                    else tr("No records yet. Press c to create.")
                ],
                footer,
                selected if items else -1,
            )
            return
        self.ui.screen.erase()
        self.box(1, 2, 3, width - 4)
        self.write(2, 4, "brig", 8, self.ui.accent)
        self.write(
            2, 13, tr("Isolated development workspaces"), width - 28, curses.A_DIM
        )
        self.write(2, width - 13, tr("WORKSPACE"), 9, self.styles["focus"])
        x = 4
        for index, label in enumerate(tabs):
            label = tr(label)
            if read_only and index != tab:
                continue
            text = f"[ {label} ]" if index == tab else f"  {label}  "
            self.write(
                5,
                x,
                text,
                len(text),
                self.styles["focus"] if index == tab else curses.A_DIM,
            )
            x += len(text) + 2
        sidebar = min(42, max(30, width // 3))
        body_height = height - 12
        count = max(1, body_height // 7)
        start = selected // count * count
        for position, item in enumerate(items[start : start + count], start):
            y = 7 + (position - start) * 7
            focused = position == selected
            self.box(y, 2, 6, sidebar, focused=focused)
            self.write(
                y + 1, 4, item.name, sidebar - 4, curses.A_BOLD if focused else 0
            )
            state_style = self.styles.get(item.status, self.styles["border"])
            self.write(y + 2, 4, f"● {tr(item.status)}", sidebar - 4, state_style)
            self.write(y + 3, 4, item.summary, sidebar - 4)
            self.write(y + 4, 4, item.context, sidebar - 4, curses.A_DIM)
        if not items:
            self.box(7, 2, 6, sidebar)
            self.write(
                9, 4, tr("Your workspace starts here"), sidebar - 4, curses.A_BOLD
            )
            self.write(
                10,
                4,
                tr("Create a record with brig")
                if read_only
                else tr("Press c to create a record"),
                sidebar - 4,
                curses.A_DIM,
            )
        self.write(
            height - 5,
            4,
            tr("{value0} / {value1} records").format(
                value0=selected + 1 if items else 0, value1=len(items)
            ),
            sidebar - 4,
            curses.A_DIM,
        )
        panel_x = sidebar + 4
        panel_width = width - panel_x - 2
        self.box(7, panel_x, height - 11, panel_width)
        item = items[selected] if items else None
        self.write(
            8,
            panel_x + 2,
            item.name if item else tr("Welcome to Brig"),
            panel_width - 4,
            curses.A_BOLD,
        )
        details = (
            item.details
            if item
            else [
                tr("Create a profile to choose your runtimes, tools and agents."),
                tr("Then register a project folder to get started."),
            ]
        )
        available = height - 17
        overview = tr("OVERVIEW")
        if len(details) > available:
            overview += f"  {detail_offset + 1}-{min(detail_offset + available, len(details))} / {len(details)}"
        self.write(9, panel_x + 2, overview, panel_width - 4, self.styles["focus"])
        for row, line in enumerate(
            details[detail_offset : detail_offset + available], 11
        ):
            self.write(row, panel_x + 2, line, panel_width - 4)
        actions = tr("Enter  details") if read_only else tr("Enter  actions")
        self.write(
            height - 6,
            panel_x + 2,
            actions + tr("   PgUp/PgDn  scroll"),
            panel_width - 4,
            curses.A_DIM,
        )
        self.write(height - 3, 2, "─" * (width - 4), width - 4, self.styles["border"])
        for line, text in enumerate(
            textwrap.wrap(
                self.ui._text(footer), width=width - 6, max_lines=2, placeholder="..."
            )
        ):
            self.write(height - 2 + line, 3, text, width - 6, curses.A_DIM)
        self.ui.screen.refresh()
