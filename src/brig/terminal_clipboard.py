"""Text clipboard access stays on the host, outside the agent containers."""

import base64
import binascii
import os
import re
import shutil
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass

LIMIT = 1024 * 1024
OSC52 = b"\x1b]52;"
PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"
PASTE_KEYS = (
    b"\x16",
    b"\x1b[118;5u",
    b"\x1b[118;5:1u",
    b"\x1b[118;5:2u",
    b"\x1b[27;5;118~",
)
# Kitty keyboard and modifyOtherKeys encodings of a Ctrl+V press or repeat.
# Codex and OpenCode request richer kitty flags than Claude Code, so the key
# may carry alternate keys, associated text, or Caps/Num Lock modifier bits.
PASTE_KEY = re.compile(
    rb"\x1b\[(?:118(?::\d*)*;(\d+)(?::[12])?(?:;[\d:]*)?u|27;(\d+);118~)"
)
PASTE_KEY_PREFIX = re.compile(rb"\x1b(?:\[[\d;:]{0,32})?")
LOCK_MODIFIERS = 64 | 128
CTRL = 4


def paste_key(data):
    """Return the length of a leading Ctrl+V key sequence, if any."""
    match = PASTE_KEY.match(data)
    if match is None:
        return 0
    modifiers = int(match[1] or match[2]) - 1
    return match.end() if modifiers & ~LOCK_MODIFIERS == CTRL else 0


@dataclass
class Clipboard:
    read_command: tuple[str, ...] = ()
    write_command: tuple[str, ...] = ()

    def read(self):
        if not self.read_command:
            return None
        try:
            result = subprocess.run(
                self.read_command, capture_output=True, timeout=2, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode or len(result.stdout) > LIMIT:
            return None
        # Clipboard text must never inject terminal keys or paste delimiters.
        return "".join(
            char
            for char in result.stdout.decode("utf-8", errors="replace")
            if char >= " " and char != "\x7f" or char in "\r\n\t"
        ).encode()

    def write(self, data):
        if not self.write_command or len(data) > LIMIT:
            return
        with suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                self.write_command,
                input=data,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )


def host_clipboard():
    """Use argument arrays; clipboard contents are never shell commands."""
    if sys.platform == "darwin":
        return Clipboard(("pbpaste",), ("pbcopy",))
    if (
        os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME")
    ) and shutil.which("powershell.exe"):
        prefix = ("powershell.exe", "-NoProfile", "-NonInteractive", "-Command")
        encoding = "[Console]::OutputEncoding = [Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
        return Clipboard(
            (*prefix, encoding + "[Console]::Write((Get-Clipboard -Raw))"),
            (
                *prefix,
                encoding + "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
            ),
        )
    if os.environ.get("WAYLAND_DISPLAY"):
        read = (
            ("wl-paste", "--no-newline", "--type", "text")
            if shutil.which("wl-paste")
            else ()
        )
        write = (
            ("wl-copy", "--type", "text/plain;charset=utf-8")
            if shutil.which("wl-copy")
            else ()
        )
        if read or write:
            return Clipboard(read, write)
    if os.environ.get("DISPLAY"):
        if shutil.which("xclip"):
            return Clipboard(
                ("xclip", "-selection", "clipboard", "-out"),
                ("xclip", "-selection", "clipboard", "-in"),
            )
        if shutil.which("xsel"):
            return Clipboard(
                ("xsel", "--clipboard", "--output"),
                ("xsel", "--clipboard", "--input"),
            )
    return Clipboard()


class ClipboardInput:
    """Recognize explicit paste keys without touching pasted text or other keys."""

    def __init__(self, clipboard):
        self.clipboard = clipboard
        self.pending = b""
        self.pasting = False
        self.bracketed = True

    def feed(self, data, *, final=False):
        data = self.pending + data
        self.pending = b""
        output = bytearray()
        while data:
            tokens = (PASTE_END,) if self.pasting else (PASTE_START, *PASTE_KEYS)
            token = next((token for token in tokens if data.startswith(token)), None)
            if token is None and not self.pasting and (length := paste_key(data)):
                token = data[:length]
            if token:
                if token == PASTE_START:
                    self.pasting = True
                    output.extend(token)
                elif token == PASTE_END:
                    self.pasting = False
                    output.extend(token)
                else:
                    text = self.clipboard.read()
                    if text is None:
                        output.extend(token)
                    elif self.bracketed:
                        output.extend(PASTE_START + text + PASTE_END)
                    else:
                        # Login prompts may not understand bracketed paste. Do
                        # not send delimiters or submit on copied line breaks.
                        output.extend(
                            text.replace(b"\r\n", b"\n")
                            .replace(b"\r", b"\n")
                            .replace(b"\n", b" ")
                            .rstrip(b" ")
                        )
                data = data[len(token) :]
            elif not final and (
                any(token.startswith(data) for token in tokens)
                or not self.pasting
                and PASTE_KEY_PREFIX.fullmatch(data)
            ):
                self.pending = data
                break
            else:
                special = re.search(
                    b"\x1b" if self.pasting else b"[\x1b\x16]", data[1:]
                )
                length = special.start() + 1 if special else len(data)
                output.extend(data[:length])
                data = data[length:]
        return bytes(output)


class ClipboardOutput:
    """Observe bounded OSC 52 copies; terminal output itself stays unchanged."""

    def __init__(self, clipboard):
        self.clipboard = clipboard
        self.pending = b""
        self.bracketed = False
        self.protocol_pending = b""

    def feed(self, data):
        protocols = self.protocol_pending + data
        for match in re.finditer(rb"\x1b\[\?2004([hl])", protocols):
            self.bracketed = match[1] == b"h"
        self.protocol_pending = protocols[-7:]
        self.pending += data
        while True:
            start = self.pending.find(OSC52)
            if start < 0:
                self.pending = self.pending[-len(OSC52) + 1 :]
                return
            self.pending = self.pending[start:]
            end = re.search(b"\x07|\x1b\\\\", self.pending)
            if end is None:
                if len(self.pending) > LIMIT * 2:
                    self.pending = b""
                return
            content = self.pending[len(OSC52) : end.start()]
            self.pending = self.pending[end.end() :]
            selection, separator, encoded = content.partition(b";")
            if separator and selection in (b"", b"c") and encoded != b"?":
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                    decoded.decode("utf-8")
                except (binascii.Error, UnicodeDecodeError):
                    continue
                self.clipboard.write(decoded)
