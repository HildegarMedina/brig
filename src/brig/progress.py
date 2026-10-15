"""Small, dependency-free terminal status indicators for background work."""

import os
import shutil
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Thread

_verbose = ContextVar("brig_verbose", default=False)


@contextmanager
def output_options(*, verbose=False):
    token = _verbose.set(verbose)
    try:
        yield
    finally:
        _verbose.reset(token)


def verbose_output():
    return _verbose.get()


# Two masts, sails and a hull; ASCII keeps the drawing stable across fonts.
_BRIG = (
    "     |    |",
    r"    /|\  /|\ ",
    r"   /_|_\/_|_\ ",
    r"   \________/",
)
_SWAY = (0, 0, 1, 1, 2, 2, 1, 1)


def _ship_frame(index, *, sinking=False, compact=False):
    depth = min(index // 2, len(_BRIG)) if sinking else 0
    if compact:
        boat = (r"|\|\__/", " ||__ ", "  ||  ", "  |   ", "  .   ")[depth]
        wave = ("~ ", " ~")[index % 2]
        return (f"{wave}{boat}{wave}",)
    offset = " " * (2 + _SWAY[index % len(_SWAY)])
    sky = ([""] * depth + [offset + row for row in _BRIG])[: len(_BRIG)]
    if depth == len(_BRIG):
        sky[-1] = offset + ("    o" if index % 4 < 2 else "     .")
    sea = "~   ~  ~   " * 4
    phase = index % 11
    return (*sky, "  " + sea[phase : phase + 26])


def _animate(stop, render):
    index = 0
    while not stop.wait(0.16):
        index += 1
        render(index)


@contextmanager
def progress(message, *, animation="sailing"):
    stream = sys.stderr
    encoding = stream.encoding or "utf-8"
    message = message.encode(encoding, errors="replace").decode(encoding)
    animated = (
        stream.isatty()
        and os.environ.get("TERM", "dumb") != "dumb"
        and not os.environ.get("CI")
        and not os.environ.get("BRIG_NO_ANIMATION")
    )
    if not animated:
        print(f"  {message}", file=stream, flush=True)
        yield
        return

    unicode = "✓".encode(encoding, errors="replace").decode(encoding) == "✓"
    size = shutil.get_terminal_size((80, 24))
    width = max(1, size.columns - 1)
    multiline = width >= 32 and size.lines >= 8
    rows = len(_BRIG) + 2
    color = "NO_COLOR" not in os.environ
    sinking = animation == "sinking"

    def line(text):
        text = text[:width].ljust(width)
        return f"\033[36m{text}\033[0m" if color else text

    def render(index):
        art = _ship_frame(index, sinking=sinking, compact=not multiline)
        if multiline:
            block = (*art, f"  {message}")
            stream.write(f"\033[{rows}A" + "".join(line(row) + "\r\n" for row in block))
        else:
            stream.write("\r" + line(f"  {message}  {art[0]}") + "\r")
        stream.flush()

    stop = Event()
    worker = Thread(target=_animate, args=(stop, render), daemon=True)
    if multiline:
        stream.write("\r" + "\n" * rows)
    render(0)
    worker.start()
    symbol = "!"
    try:
        yield
        symbol = "✓" if unicode else "+"
    finally:
        stop.set()
        worker.join()
        if multiline:
            stream.write(f"\033[{rows}A" + "\033[2K\r\n" * rows + f"\033[{rows}A")
        stream.write("\r" + line(f"  {symbol} {message}") + "\r\n")
        stream.flush()
