"""Card rendering and command output under different terminal capabilities."""

import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from brig.persistence.store import JsonStateStore
from brig.ui.cards import _width, render_cards
from brig.ui.cli import main
from tests.demo_engine import DemoEngine
from tests.fakes import demo_state


class TerminalOutput(io.StringIO):
    @property
    def encoding(self):
        return "utf-8"

    def isatty(self):
        return True


class CardTests(unittest.TestCase):
    def render(self, records, *, columns=45, environment=None):
        with (
            redirect_stdout(TerminalOutput()),
            patch.dict("os.environ", environment or {"TERM": "xterm"}, clear=True),
            patch(
                "brig.ui.cards.shutil.get_terminal_size",
                return_value=os.terminal_size((columns, 24)),
            ),
        ):
            return render_cards(records, "plain listing")

    def test_list_commands_show_colored_cards_with_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            JsonStateStore(Path(directory)).save(demo_state())
            for command in ("profile", "project"):
                output = TerminalOutput()
                with (
                    self.subTest(command=command),
                    redirect_stdout(output),
                    patch.dict("os.environ", {"TERM": "xterm"}, clear=True),
                    patch("brig.ui.cli.DockerEngine", return_value=DemoEngine()),
                ):
                    status = main(["--data-dir", directory, command, "list"])
                self.assertEqual(status, 0)
                contents = output.getvalue()
                self.assertIn("┌", contents)
                self.assertIn("\033[36m", contents)
                self.assertIn("\033[35m", contents)
                self.assertIn("Runtimes", contents)
                self.assertIn("Agents", contents)
                if command == "project":
                    self.assertIn("Status", contents)
                    self.assertIn("Folder", contents)

    def test_redirected_output_keeps_original_summary(self):
        with redirect_stdout(io.StringIO()):
            result = render_cards([("Name", ["Details"])], "original summary")
        self.assertEqual(result, "original summary")

    def test_no_color_keeps_cards_without_escape_sequences(self):
        result = self.render(
            [("Name", ["Details"])], environment={"TERM": "xterm", "NO_COLOR": "1"}
        )
        self.assertIn("┌", result)
        self.assertNotIn("\033", result)

    def test_dumb_terminal_uses_ascii_without_colors(self):
        result = self.render([("Name", ["Details"])], environment={"TERM": "dumb"})
        self.assertTrue(result.startswith("+"))
        self.assertNotIn("\033", result)
        result.encode("ascii")

    def test_narrow_cards_wrap_wide_text_and_remove_control_characters(self):
        text = "A very long project folder /home/开发/" + "x" * 60
        result = self.render([("Title\033\n", [text])], columns=30)
        plain = re.sub(r"\033\[[0-9;]*m", "", result)
        for line in plain.splitlines():
            self.assertEqual(_width(line), 29)
        self.assertNotIn("\033", plain)
        self.assertIn("开发", plain)

    def test_very_small_terminal_falls_back_to_plain_summary(self):
        self.assertEqual(
            self.render([("Name", ["Details"])], columns=15), "plain listing"
        )
