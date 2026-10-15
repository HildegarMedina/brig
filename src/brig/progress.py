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


def _animate(stop, render, frames):
    index = 0
    while not stop.wait(0.09):
        index = (index + 1) % len(frames)
        render(frames[index])


@contextmanager
def progress(message):
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

    unicode = "⠋✓".encode(encoding, errors="replace").decode(encoding) == "⠋✓"
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if unicode else "|/-\\"
    width = max(1, shutil.get_terminal_size((80, 24)).columns - 1)
    color = "NO_COLOR" not in os.environ

    def render(symbol):
        line = f"  {symbol} {message}"[:width].ljust(width)
        if color:
            line = f"\033[36m{line}\033[0m"
        stream.write("\r" + line + "\r")
        stream.flush()

    stop = Event()
    worker = Thread(target=_animate, args=(stop, render, frames), daemon=True)
    render(frames[0])
    worker.start()
    symbol = "!"
    try:
        yield
        symbol = "✓" if unicode else "+"
    finally:
        stop.set()
        worker.join()
        render(symbol)
        stream.write("\n")
        stream.flush()
