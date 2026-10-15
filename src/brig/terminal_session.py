"""Relay an interactive agent PTY while keeping desktop clipboard access local."""

import errno
import os
import pty
import select
import signal
import subprocess
import sys
import termios
import tty

from brig.terminal_clipboard import ClipboardInput, ClipboardOutput, host_clipboard


def _write(descriptor, data):
    while data:
        size = os.write(descriptor, data)
        data = data[size:]


def _relay(master, input_fd, output_fd, clipboard):
    incoming = ClipboardInput(clipboard)
    incoming.bracketed = False
    outgoing = ClipboardOutput(clipboard)
    inputs = [master, input_fd]
    while True:
        ready, _, _ = select.select(inputs, [], [], 0.05 if incoming.pending else None)
        if not ready:
            _write(master, incoming.feed(b"", final=True))
        if master in ready:
            try:
                data = os.read(master, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                return
            if not data:
                return
            outgoing.feed(data)
            incoming.bracketed = outgoing.bracketed
            _write(output_fd, data)
        if input_fd in ready:
            data = os.read(input_fd, 65536)
            if not data:
                inputs.remove(input_fd)
                _write(master, incoming.feed(b"", final=True))
            else:
                _write(master, incoming.feed(data))


def run_agent_terminal(args, *, runner=subprocess.run):
    # Custom runners remain useful for embedding and tests. Redirected commands
    # keep their normal streams and never access the host clipboard.
    if runner is not subprocess.run or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return runner(args, check=False)
    clipboard = host_clipboard()
    if not (clipboard.read_command or clipboard.write_command):
        return runner(args, check=False)
    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    original = termios.tcgetattr(input_fd)
    size = termios.tcgetwinsize(input_fd)
    pid, master = pty.fork()
    if pid == 0:
        try:
            termios.tcsetwinsize(0, size)
            os.execvp(args[0], args)
        except OSError:
            os._exit(127)

    def resize(signum=None, frame=None):
        termios.tcsetwinsize(master, termios.tcgetwinsize(input_fd))

    previous = signal.signal(signal.SIGWINCH, resize)
    try:
        tty.setraw(input_fd)
        resize()
        _relay(master, input_fd, output_fd, clipboard)
    finally:
        termios.tcsetattr(input_fd, termios.TCSADRAIN, original)
        signal.signal(signal.SIGWINCH, previous)
        os.close(master)
        _, status = os.waitpid(pid, 0)
    return subprocess.CompletedProcess(args, os.waitstatus_to_exitcode(status))
