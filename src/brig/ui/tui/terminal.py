"""Reusable curses rendering, input and terminal suspension."""

import curses
import locale
import os
import textwrap
from collections.abc import Callable

from brig.errors import BrigError, Cancelled


class Terminal:
    def __init__(self, screen):
        self.screen = screen
        screen.keypad(True)
        if "ESCDELAY" not in os.environ:
            # Distinguish Esc from arrow-key sequences without a one-second pause.
            curses.set_escdelay(100)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.accent = curses.A_BOLD
        self.error_style = curses.A_BOLD
        if "NO_COLOR" not in os.environ and curses.has_colors():
            try:
                curses.start_color()
                background = -1
                try:
                    curses.use_default_colors()
                except curses.error:
                    background = curses.COLOR_BLACK
                curses.init_pair(1, curses.COLOR_CYAN, background)
                curses.init_pair(2, curses.COLOR_RED, background)
                self.accent |= curses.color_pair(1)
                self.error_style |= curses.color_pair(2)
            except curses.error:
                # Basic attributes still work on terminals with limited colors.
                pass

    @staticmethod
    def _text(text: str) -> str:
        encoding = locale.getencoding()
        try:
            text.encode(encoding)
        except UnicodeEncodeError:
            text = text.translate(
                str.maketrans(
                    {
                        "↑": "up",
                        "↓": "/down",
                        "›": ">",
                        "▏": "|",
                        "×": "x",
                        "·": "|",
                        "—": "-",
                        "→": "->",
                    }
                )
            )
            text = text.encode(encoding, errors="replace").decode(encoding)
        return text

    @staticmethod
    def _capacity(height: int, error: bool = False) -> int:
        return max(1, height - 9 - error)

    def _write(self, y: int, x: int, text: str, style: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if 0 <= y < height and 0 <= x < width - 1:
            safe = self._text("".join(c if c.isprintable() else " " for c in text))
            try:
                self.screen.addnstr(y, x, safe, width - x - 1, style)
            except curses.error:
                pass

    def render(
        self,
        title: str,
        rows: list[str],
        footer: str,
        selected: int = -1,
        *,
        error_message: str | None = None,
        error_rows: bool = False,
    ) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self._write(1, 2, "[ brig ]", self.accent)
        self._write(1, 12, "isolated project environments", curses.A_DIM)
        if height < 12 or width < 45:
            self._write(3, 1, "Resize terminal to at least 45 × 12.")
            self.screen.refresh()
            return
        self._write(3, 2, title, curses.A_BOLD)
        self._write(4, 2, "-" * (width - 5), curses.A_DIM)
        capacity = self._capacity(height, bool(error_message))
        offset = max(0, selected - capacity + 1)
        if len(rows) > capacity:
            position = (
                f" {offset + 1}-{min(offset + capacity, len(rows))} / {len(rows)} "
            )
            self._write(4, width - len(position) - 3, position, curses.A_DIM)
        for index, row in enumerate(rows[offset : offset + capacity], offset):
            is_selected = index == selected
            style = self.error_style if error_rows else 0
            if is_selected:
                style |= self.accent | curses.A_REVERSE
            elif row.startswith("[x]"):
                style |= self.accent
            label = self._text(("› " if is_selected else "  ") + row)
            self._write(
                5 + index - offset,
                2,
                label.ljust(width - 5) if is_selected else label,
                style,
            )
        if error_message:
            self._write(height - 5, 2, f"Error: {error_message}", self.error_style)
        self._write(height - 4, 2, "-" * (width - 5), curses.A_DIM)
        help_lines = textwrap.wrap(
            self._text(footer), width=width - 5, max_lines=2, placeholder="..."
        )
        for index, line in enumerate(help_lines):
            self._write(height - 3 + index, 2, line, curses.A_DIM)
        self.screen.refresh()

    def loading(self, message: str) -> None:
        self.render(
            "Version catalog", [message], "Fetching published versions · Ctrl+C cancel"
        )

    def external(self, action):
        """Give Docker progress and interactive shells a normal terminal."""
        curses.def_prog_mode()
        curses.endwin()
        try:
            return action()
        finally:
            curses.reset_prog_mode()
            self.screen.refresh()

    def key(self):
        key = self.screen.get_wch()
        if key in ("\x03", "\x04"):
            raise KeyboardInterrupt
        return key

    def choose(
        self,
        title: str,
        options: list[str],
        default: int = 0,
        *,
        searchable: bool = False,
    ) -> int:
        if not options:
            raise BrigError("No options available.")
        selected = min(default, len(options) - 1)
        query = ""
        while True:
            indices = [
                i
                for i, value in enumerate(options)
                if query.casefold() in value.casefold()
            ]
            if selected not in indices and indices:
                selected = indices[0]
            position = indices.index(selected) if selected in indices else -1
            footer = "↑↓ move · enter select · esc back"
            if searchable:
                footer += " · / search"
            rows = [options[i] for i in indices] or [
                "No matches. Press / to change search."
            ]
            self.render(
                title + (f" · search: {query}" if query else ""), rows, footer, position
            )
            key = self.key()
            if key in ("\x1b", "q"):
                raise Cancelled
            if key in (curses.KEY_UP, "k") and indices:
                selected = indices[(position - 1) % len(indices)]
            elif key in (curses.KEY_DOWN, "j") and indices:
                selected = indices[(position + 1) % len(indices)]
            elif key in ("\n", "\r", curses.KEY_ENTER) and indices:
                return selected
            elif key == "/" and searchable:
                query = self.input("Search", query)

    def multiple(
        self,
        title: str,
        options: list[str],
        defaults: set[str],
        *,
        required_message: str | None = None,
    ) -> list[str]:
        chosen = set(defaults).intersection(options)
        selected = 0
        error = None
        while True:
            rows = [
                f"[{'x' if option in chosen else ' '}] {option}" for option in options
            ]
            self.render(
                title,
                rows,
                "↑↓ move · space toggle · enter next · esc back",
                selected,
                error_message=error,
            )
            key = self.key()
            if key == "\x1b":
                raise Cancelled
            if key in (curses.KEY_UP, "k"):
                selected = (selected - 1) % len(options)
            elif key in (curses.KEY_DOWN, "j"):
                selected = (selected + 1) % len(options)
            elif key == " ":
                option = options[selected]
                chosen.symmetric_difference_update({option})
                if chosen:
                    error = None
            elif key in ("\n", "\r", curses.KEY_ENTER):
                if required_message and not chosen:
                    error = required_message
                    continue
                return [option for option in options if option in chosen]

    def input(
        self,
        title: str,
        default: str = "",
        *,
        required_message: str | None = None,
        validator: Callable[[str], str] | None = None,
    ) -> str:
        value = default
        error = None
        while True:
            self.render(
                title,
                [value + "▏"],
                "type to edit · ctrl+u clear · enter continue · esc cancel",
                error_message=error,
            )
            key = self.key()
            if key == "\x1b":
                raise Cancelled
            if key in ("\n", "\r", curses.KEY_ENTER):
                if required_message and not value.strip():
                    error = required_message
                    continue
                try:
                    return validator(value.strip()) if validator else value.strip()
                except BrigError as validation_error:
                    error = str(validation_error)
                    continue
            if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                value = value[:-1]
            elif key == "\x15":
                value = ""
            elif isinstance(key, str) and key.isprintable():
                value += key
            if value.strip():
                error = None

    def notice(self, title: str, lines: list[str], *, error: bool = False) -> None:
        offset = 0
        while True:
            height, _ = self.screen.getmaxyx()
            maximum = max(0, len(lines) - self._capacity(height))
            offset = min(offset, maximum)
            self.render(
                title, lines[offset:], "↑↓ scroll · enter / esc close", error_rows=error
            )
            key = self.key()
            if key in ("\n", "\r", "\x1b", "q", curses.KEY_ENTER):
                return
            if key == curses.KEY_DOWN:
                offset = min(offset + 1, maximum)
            elif key == curses.KEY_UP:
                offset = max(offset - 1, 0)

    def confirm(self, title: str, lines: list[str], *, action: str = "Save") -> bool:
        self.notice(title, lines)
        return (
            self.choose(
                "Save these changes?" if action == "Save" else f"{action}?",
                [action, "Cancel"],
                default=0 if action == "Save" else 1,
            )
            == 0
        )
