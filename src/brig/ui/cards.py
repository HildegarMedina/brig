"""Terminal cards with plain output for pipes and basic terminal fallbacks."""

import os
import shutil
import sys
import unicodedata

PALETTE = (36, 35, 34, 33, 32, 31)


def _width(text: str) -> int:
    return sum(
        0
        if unicodedata.combining(char)
        else 2
        if unicodedata.east_asian_width(char) in ("W", "F")
        else 1
        for char in text
    )


def _wrap(text: str, width: int) -> list[str]:
    text = "".join(char if char.isprintable() else " " for char in text)
    lines = []
    line = ""
    for char in text:
        if line and _width(line + char) > width:
            lines.append(line)
            line = ""
        line += char
    return [*lines, line]


def render_cards(records: list[tuple[str, list[str]]], plain: str) -> str:
    stream = sys.stdout
    columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    if not stream.isatty() or columns < 20:
        return plain
    width = min(72, columns - 1)
    inner = width - 4
    encoding = stream.encoding or "ascii"
    try:
        "┌─┐│└┘".encode(encoding)
        unicode = os.environ.get("TERM") != "dumb"
    except (UnicodeEncodeError, LookupError):
        unicode = False
    top_left, horizontal, top_right, vertical, bottom_left, bottom_right = (
        "┌─┐│└┘" if unicode else "+-+|++"
    )
    colors = "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    cards = []
    for index, (title, details) in enumerate(records):
        color = f"\033[{PALETTE[index % len(PALETTE)]}m" if colors else ""
        reset = "\033[0m" if colors else ""

        def border(text: str, color=color, reset=reset) -> str:
            return f"{color}{text}{reset}"

        lines = [border(top_left + horizontal * (width - 2) + top_right)]
        for heading, text in [
            (True, title),
            (False, ""),
            *[(False, value) for value in details],
        ]:
            for part in _wrap(text, inner):
                safe = part.encode(encoding, errors="replace").decode(encoding)
                padding = " " * (inner - _width(safe))
                content = f"{color}\033[1m{safe}{reset}" if heading and colors else safe
                lines.append(
                    f"{border(vertical)} {content}{padding} {border(vertical)}"
                )
        lines.append(border(bottom_left + horizontal * (width - 2) + bottom_right))
        cards.append("\n".join(lines))
    return "\n\n".join(cards)
