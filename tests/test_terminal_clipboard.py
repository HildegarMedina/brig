"""Host clipboard adapters and byte-transparent terminal clipboard protocols."""

import base64
import errno
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, call, patch

from brig.terminal_clipboard import (
    LIMIT,
    OSC52,
    PASTE_END,
    PASTE_KEYS,
    PASTE_START,
    Clipboard,
    ClipboardInput,
    ClipboardOutput,
    host_clipboard,
)
from brig.terminal_session import _relay, _write, run_agent_terminal


class ClipboardTests(unittest.TestCase):
    def test_host_helpers_are_selected_without_forwarding_display_services(self):
        cases = [
            ("darwin", {}, set(), "pbpaste", "pbcopy"),
            (
                "linux",
                {"WSL_INTEROP": "fixture"},
                {"powershell.exe"},
                "powershell.exe",
                "powershell.exe",
            ),
            ("linux", {"WSL_DISTRO_NAME": "fixture"}, set(), None, None),
            (
                "linux",
                {"WAYLAND_DISPLAY": "wayland-0"},
                {"wl-paste", "wl-copy"},
                "wl-paste",
                "wl-copy",
            ),
            ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, {"wl-paste"}, "wl-paste", None),
            ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, {"wl-copy"}, None, "wl-copy"),
            (
                "linux",
                {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"},
                {"xclip"},
                "xclip",
                "xclip",
            ),
            ("linux", {"DISPLAY": ":0"}, {"xclip"}, "xclip", "xclip"),
            ("linux", {"DISPLAY": ":0"}, {"xsel"}, "xsel", "xsel"),
            ("linux", {"DISPLAY": ":0"}, set(), None, None),
            ("linux", {}, {"xclip", "wl-copy"}, None, None),
        ]
        for platform, environment, installed, reader, writer in cases:
            with (
                self.subTest(
                    platform=platform, environment=environment, installed=installed
                ),
                patch("brig.terminal_clipboard.sys.platform", platform),
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "brig.terminal_clipboard.shutil.which",
                    side_effect=lambda name, installed=installed: (
                        name if name in installed else None
                    ),
                ),
            ):
                clipboard = host_clipboard()
                self.assertEqual(next(iter(clipboard.read_command), None), reader)
                self.assertEqual(next(iter(clipboard.write_command), None), writer)

    def test_reads_preserve_unicode_and_lines_but_cannot_inject_paste_end(self):
        clipboard = Clipboard(("reader",), ("writer",))
        text = "café\nlinea\t\r\x1b[201~\x03\x7f`$(literal)`"
        with patch(
            "brig.terminal_clipboard.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, text.encode()),
        ) as run:
            self.assertEqual(
                clipboard.read(), "café\nlinea\t\r[201~`$(literal)`".encode()
            )
        self.assertNotIn("input", run.call_args.kwargs)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.args, (("reader",),))
        self.assertIsNone(Clipboard().read())
        for result in (
            subprocess.CompletedProcess([], 1, b""),
            subprocess.CompletedProcess([], 0, b"x" * (LIMIT + 1)),
        ):
            with patch("brig.terminal_clipboard.subprocess.run", return_value=result):
                self.assertIsNone(clipboard.read())
        for error in (OSError(), subprocess.TimeoutExpired("reader", 2)):
            with patch("brig.terminal_clipboard.subprocess.run", side_effect=error):
                self.assertIsNone(clipboard.read())

    def test_copy_uses_stdin_and_never_prints_clipboard_contents(self):
        clipboard = Clipboard(write_command=("writer",))
        with patch("brig.terminal_clipboard.subprocess.run") as run:
            clipboard.write(b"literal $(text)")
            self.assertEqual(run.call_args.kwargs["input"], b"literal $(text)")
            self.assertEqual(run.call_args.args, (("writer",),))
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
            self.assertNotIn("shell", run.call_args.kwargs)
            run.reset_mock()
            Clipboard().write(b"text")
            clipboard.write(b"x" * (LIMIT + 1))
            run.assert_not_called()
        with patch("brig.terminal_clipboard.subprocess.run", side_effect=OSError()):
            clipboard.write(b"text")

    def test_every_paste_key_can_arrive_in_fragments(self):
        clipboard = Mock()
        clipboard.read.return_value = "hola\nmundo 🛳".encode()
        expected = PASTE_START + clipboard.read.return_value + PASTE_END
        for key in PASTE_KEYS:
            with self.subTest(key=key):
                stream = ClipboardInput(clipboard)
                received = b"".join(stream.feed(bytes([byte])) for byte in key)
                self.assertEqual(received, expected)
        clipboard.read.return_value = None
        self.assertEqual(ClipboardInput(clipboard).feed(b"\x16"), b"\x16")
        clipboard.read.return_value = b""
        self.assertEqual(
            ClipboardInput(clipboard).feed(b"\x16"), PASTE_START + PASTE_END
        )

    def test_rich_kitty_encodings_of_ctrl_v_paste_and_other_keys_do_not(self):
        # Codex and OpenCode enable more kitty keyboard flags than Claude Code.
        clipboard = Mock()
        clipboard.read.return_value = b"text"
        expected = PASTE_START + b"text" + PASTE_END
        for key in (
            b"\x1b[118;69u",
            b"\x1b[118;133u",
            b"\x1b[118;197:1u",
            b"\x1b[118::86;5u",
            b"\x1b[118:86:118;5:2u",
            b"\x1b[118;5;0u",
            b"\x1b[27;133;118~",
        ):
            with self.subTest(key=key):
                stream = ClipboardInput(clipboard)
                received = b"".join(stream.feed(bytes([byte])) for byte in key)
                self.assertEqual(received + stream.feed(b"", final=True), expected)
        clipboard.read.reset_mock()
        for key in (
            b"\x1b[118;5:3u",
            b"\x1b[118;6u",
            b"\x1b[118;7u",
            b"\x1b[118;13u",
            b"\x1b[119;5u",
            b"\x1b[1;5A",
        ):
            with self.subTest(key=key):
                stream = ClipboardInput(clipboard)
                received = b"".join(stream.feed(bytes([byte])) for byte in key)
                self.assertEqual(received + stream.feed(b"", final=True), key)
        stream = ClipboardInput(clipboard)
        pasted = PASTE_START + b"\x1b[118;133u" + PASTE_END
        self.assertEqual(stream.feed(pasted), pasted)
        clipboard.read.assert_not_called()

    def test_terminal_pastes_other_keys_and_large_payloads_pass_unchanged(self):
        clipboard = Mock()
        stream = ClipboardInput(clipboard)
        data = (
            PASTE_START
            + b"x" * LIMIT
            + b"\x16\x1b[118;5u"
            + PASTE_END
            + b"\x1b[A\x03text"
        )
        split = len(PASTE_START) - 1
        self.assertEqual(stream.feed(data[:split]) + stream.feed(data[split:]), data)
        clipboard.read.assert_not_called()
        self.assertEqual(stream.feed(b"\x1b"), b"")
        self.assertEqual(stream.feed(b"", final=True), b"\x1b")
        # A marker split across reads must not turn pasted Ctrl+V into a new paste.
        stream = ClipboardInput(clipboard)
        self.assertEqual(
            b"".join(
                stream.feed(bytes([byte])) for byte in PASTE_START + b"\x16" + PASTE_END
            ),
            PASTE_START + b"\x16" + PASTE_END,
        )

    def test_plain_login_prompts_get_text_without_markers_or_submit_keys(self):
        clipboard = Mock()
        clipboard.read.return_value = b"one\r\ntwo\rthree\n"
        stream = ClipboardInput(clipboard)
        stream.bracketed = False
        self.assertEqual(stream.feed(b"\x16"), b"one two three")
        output = ClipboardOutput(clipboard)
        for byte in b"\x1b[?2004h":
            output.feed(bytes([byte]))
        self.assertTrue(output.bracketed)
        output.feed(b"\x1b[?2004l")
        self.assertFalse(output.bracketed)

    def test_copy_recognizes_fragmented_osc52_bel_and_st_without_queries(self):
        clipboard = Mock()
        stream = ClipboardOutput(clipboard)
        encoded = base64.b64encode("texto 🛳".encode())
        data = (
            b"normal output"
            + OSC52
            + b"c;"
            + encoded
            + b"\x07"
            + OSC52
            + b";"
            + encoded
            + b"\x1b\\"
        )
        for byte in data:
            stream.feed(bytes([byte]))
        self.assertEqual(clipboard.write.call_args_list, [call("texto 🛳".encode())] * 2)
        clipboard.reset_mock()
        for payload in (b"c", b"c;?", b"p;" + encoded, b"c;invalid!", b"c;/w=="):
            stream.feed(OSC52 + payload + b"\x07")
        stream.feed(OSC52 + b"c;" + b"x" * (LIMIT * 2))
        self.assertEqual(stream.pending, b"")
        clipboard.write.assert_not_called()
        stream.feed(
            OSC52 + b"c;" + encoded + b"\x07" + OSC52 + b"c;" + encoded + b"\x07"
        )
        self.assertEqual(clipboard.write.call_count, 2)


class TerminalSessionTests(unittest.TestCase):
    def test_partial_writes_are_completed(self):
        with patch("brig.terminal_session.os.write", side_effect=[2, 3]) as write:
            _write(5, b"hello")
        self.assertEqual(write.call_args_list, [call(5, b"hello"), call(5, b"llo")])

    def test_relay_handles_paste_partial_keys_eof_copy_and_raw_output(self):
        clipboard = Mock()
        clipboard.read.return_value = b"paste"
        encoded = OSC52 + b"c;" + base64.b64encode(b"copy") + b"\x07"
        enable = b"\x1b[?2004h"
        reads = [enable, b"\x1b", b"\x16", encoded, b"", b""]
        ready = [
            ([1], [], []),
            ([2], [], []),
            ([], [], []),
            ([2], [], []),
            ([1], [], []),
            ([2], [], []),
            ([1], [], []),
        ]
        with (
            patch("brig.terminal_session.select.select", side_effect=ready),
            patch("brig.terminal_session.os.read", side_effect=reads),
            patch("brig.terminal_session._write") as write,
        ):
            _relay(1, 2, 3, clipboard)
        clipboard.write.assert_called_once_with(b"copy")
        self.assertIn(call(1, b"\x1b"), write.call_args_list)
        self.assertIn(call(1, PASTE_START + b"paste" + PASTE_END), write.call_args_list)
        self.assertIn(call(3, encoded), write.call_args_list)

    def test_pty_eio_is_normal_eof_other_io_errors_propagate(self):
        for error in (OSError(errno.EIO, "closed"), OSError(errno.EBADF, "bad fd")):
            with (
                patch(
                    "brig.terminal_session.select.select", return_value=([1], [], [])
                ),
                patch("brig.terminal_session.os.read", side_effect=error),
            ):
                if error.errno == errno.EIO:
                    _relay(1, 2, 3, Mock())
                else:
                    with self.assertRaises(OSError):
                        _relay(1, 2, 3, Mock())

    def test_custom_runners_redirected_streams_and_missing_helpers_use_original_io(
        self,
    ):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0))
        run_agent_terminal(["fixture"], runner=runner)
        runner.assert_called_once_with(["fixture"], check=False)
        # Wrap the real default runner so its identity check remains meaningful.
        for terminal, clipboard in ((False, Clipboard()), (True, Clipboard())):
            with (
                patch("sys.stdin", Mock(isatty=Mock(return_value=terminal))),
                patch("sys.stdout", Mock(isatty=Mock(return_value=terminal))),
                patch("brig.terminal_session.host_clipboard", return_value=clipboard),
            ):
                result = run_agent_terminal([sys.executable, "-c", "pass"])
            self.assertEqual(result.returncode, 0)

    def session_patches(self, stack, *, child=False):
        stack.enter_context(
            patch(
                "sys.stdin",
                Mock(isatty=Mock(return_value=True), fileno=Mock(return_value=10)),
            )
        )
        stack.enter_context(
            patch(
                "sys.stdout",
                Mock(isatty=Mock(return_value=True), fileno=Mock(return_value=11)),
            )
        )
        stack.enter_context(
            patch(
                "brig.terminal_session.host_clipboard",
                return_value=Clipboard(("read",), ("write",)),
            )
        )
        stack.enter_context(
            patch("brig.terminal_session.termios.tcgetattr", return_value=["original"])
        )
        stack.enter_context(
            patch("brig.terminal_session.termios.tcgetwinsize", return_value=(28, 90))
        )
        stack.enter_context(
            patch(
                "brig.terminal_session.pty.fork", return_value=(0 if child else 42, 12)
            )
        )
        resize = stack.enter_context(
            patch("brig.terminal_session.termios.tcsetwinsize")
        )
        signals = stack.enter_context(
            patch("brig.terminal_session.signal.signal", return_value=signal.SIG_DFL)
        )
        stack.enter_context(patch("brig.terminal_session.tty.setraw"))
        restore = stack.enter_context(patch("brig.terminal_session.termios.tcsetattr"))
        close = stack.enter_context(patch("brig.terminal_session.os.close"))
        stack.enter_context(
            patch("brig.terminal_session.os.waitpid", return_value=(42, 7 << 8))
        )
        relay = stack.enter_context(patch("brig.terminal_session._relay"))
        return resize, signals, restore, close, relay

    def test_session_restores_terminal_and_resize_handler_on_success_and_failure(self):
        for fail in (False, True):
            with ExitStack() as stack:
                resize, signals, restore, close, relay = self.session_patches(stack)
                if fail:
                    relay.side_effect = RuntimeError("fixture")
                    with self.assertRaises(RuntimeError):
                        run_agent_terminal(["fixture"])
                else:
                    result = run_agent_terminal(["fixture"])
                    self.assertEqual(result.returncode, 7)
                    signals.call_args_list[0].args[1](signal.SIGWINCH, None)
                resize.assert_called_with(12, (28, 90))
                restore.assert_called_once()
                close.assert_called_once_with(12)
                self.assertEqual(
                    signals.call_args_list[-1], call(signal.SIGWINCH, signal.SIG_DFL)
                )

    def test_child_sets_size_and_execs_argv_without_shell(self):
        with ExitStack() as stack:
            resize, _, _, _, _ = self.session_patches(stack, child=True)
            execute = stack.enter_context(
                patch("brig.terminal_session.os.execvp", side_effect=OSError())
            )
            exit_child = stack.enter_context(
                patch("brig.terminal_session.os._exit", side_effect=SystemExit(127))
            )
            with self.assertRaises(SystemExit):
                run_agent_terminal(["fixture", "literal $(argument)"])
            resize.assert_called_once_with(0, (28, 90))
            execute.assert_called_once_with(
                "fixture", ["fixture", "literal $(argument)"]
            )
            exit_child.assert_called_once_with(127)

    def test_real_pty_pastes_copies_resizes_and_restores_the_host_terminal(self):
        with tempfile.TemporaryDirectory() as folder:
            copied = Path(folder) / "clipboard.txt"
            text = "texto del host\nsegunda línea 🛳"
            child = """import base64, os, signal, termios, tty
tty.setraw(0)
signal.signal(signal.SIGWINCH, lambda *_: os.write(1, b"RESIZED=" + repr(termios.tcgetwinsize(0)).encode()))
os.write(1, b"\\x1b[?2004h\\x1b]52;c;" + base64.b64encode("copiado 🛳".encode()) + b"\\x07READY")
data=b""
while not data.endswith(b"\\x1b[201~"):
 data+=os.read(0,65536)
os.write(1, b"PAYLOAD="+data.hex().encode())
raise SystemExit(7)
"""
            harness = f"""import subprocess, sys, termios
from unittest.mock import patch
from brig.terminal_clipboard import Clipboard
from brig.terminal_session import run_agent_terminal
original=termios.tcgetattr(0)
clipboard=Clipboard(
 (sys.executable,"-c",{("import sys; sys.stdout.buffer.write(" + repr(text.encode()) + ")")!r}),
 (sys.executable,"-c",{("import sys; from pathlib import Path; Path(" + repr(str(copied)) + ").write_bytes(sys.stdin.buffer.read())")!r}),
)
with patch("brig.terminal_session.host_clipboard",return_value=clipboard):
 result=run_agent_terminal([sys.executable,"-c",{child!r}])
print("STATUS="+str(result.returncode),flush=True)
print("RESTORED="+str(original==termios.tcgetattr(0)),flush=True)
"""
            master, slave = pty.openpty()
            termios.tcsetwinsize(slave, (28, 90))
            process = subprocess.Popen(
                [sys.executable, "-c", harness],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
            )
            os.close(slave)
            output = b""
            sent_resize = sent_paste = False
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            output += os.read(master, 65536)
                        except OSError:
                            break
                    if b"READY" in output and not sent_resize:
                        termios.tcsetwinsize(master, (35, 110))
                        os.kill(process.pid, signal.SIGWINCH)
                        sent_resize = True
                    if b"RESIZED=(35, 110)" in output and not sent_paste:
                        os.write(master, b"\x1b[118;5u")
                        sent_paste = True
                self.assertIn(b"STATUS=7", output)
                self.assertIn(b"RESTORED=True", output)
                self.assertIn(
                    b"PAYLOAD="
                    + (PASTE_START + text.encode() + PASTE_END).hex().encode(),
                    output,
                )
                self.assertEqual(copied.read_text(), "copiado 🛳")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                os.close(master)
