"""Bracketed paste delivery and terminal protocol bookkeeping."""

import curses
import io
import unittest
from unittest.mock import patch

from brig.ui.tui.terminal import (
    ENABLE_PROTOCOLS,
    RESTORE_PROTOCOLS,
    Paste,
    _flatten_paste,
    _read_paste,
    _visible,
    tui_protocols,
)
from tests import test_tui


def scripted(characters):
    remaining = list(characters)

    def read(wait):
        return remaining.pop(0) if remaining else None

    return read


class TtyStream(io.StringIO):
    def isatty(self):
        return True


class PasteTests(unittest.TestCase):
    def test_read_paste_decodes_complete_marker_pairs(self):
        reader = scripted(list("[200~brig\x1b[201~"))
        self.assertEqual(_read_paste(reader), "brig")

    def test_read_paste_rejects_plain_esc_and_unknown_sequences(self):
        self.assertIsNone(_read_paste(scripted([])))
        self.assertIsNone(_read_paste(scripted(list("[201~"))))
        self.assertIsNone(_read_paste(scripted(list("[200"))))
        self.assertIsNone(
            _read_paste(scripted(["[", "2", curses.KEY_UP, "0", "~", "x"]))
        )

    def test_read_paste_ends_incomplete_bursts_and_keeps_embedded_esc(self):
        reader = scripted(list("[200~one\x1b two"))
        self.assertEqual(_read_paste(reader), "one\x1b two")

    def test_read_paste_skips_decoded_key_codes_in_content(self):
        reader = scripted(["[", "2", "0", "0", "~", curses.KEY_UP, "x"])
        self.assertEqual(_read_paste(reader), "x")

    def test_key_returns_paste_objects_and_plain_escapes(self):
        ui = test_tui.TerminalTests().terminal(list("\x1b[200~pasted\x1b[201~"))
        ui.protocols = True
        key = ui.key()
        self.assertIsInstance(key, Paste)
        self.assertEqual(key.text, "pasted")
        ui = test_tui.TerminalTests().terminal(["\x1b"])
        ui.protocols = True
        self.assertEqual(ui.key(), "\x1b")
        ui = test_tui.TerminalTests().terminal(["\x1b"])
        self.assertEqual(ui.key(), "\x1b")

    def test_input_flattens_multiline_paste_into_one_line(self):
        keys = list("\x1b[200~first\r\nsecond\tthird\x1b[201~") + ["\n"]
        ui = test_tui.TerminalTests().terminal(keys)
        ui.protocols = True
        self.assertEqual(ui.input("Name"), "first second third")

    def test_empty_paste_keeps_the_required_message(self):
        keys = ["\n", *list("\x1b[200~\r\n\x1b[201~"), "\n", "v", "\n"]
        ui = test_tui.TerminalTests().terminal(keys)
        ui.protocols = True
        self.assertEqual(ui.input("Name", required_message="Enter a value"), "v")

    def test_input_shows_the_tail_of_long_values(self):
        ui = test_tui.TerminalTests().terminal(["\n"])
        self.assertEqual(ui.input("Name", "v" * 120), "v" * 120)
        self.assertTrue(
            any(row.endswith("…" + "v" * 83 + "▏") for row in ui.screen.written)
        )

    def test_menu_loops_survive_pasted_text(self):
        keys = list("\x1b[200~noise\x1b[201~") + [curses.KEY_DOWN, "\n"]
        ui = test_tui.TerminalTests().terminal(keys)
        ui.protocols = True
        self.assertEqual(ui.choose("Menu", ["one", "two"]), 1)

    def test_flatten_keeps_pasted_blocks_on_one_line(self):
        self.assertEqual(_flatten_paste("one\r\ntwo\t three "), "one two three")
        self.assertEqual(_flatten_paste("\r\n\t"), "")
        self.assertEqual(_flatten_paste("a\x1bb"), "a b")

    def test_visible_shows_short_values_and_long_tails(self):
        self.assertEqual(_visible("name", 90), "name")
        self.assertEqual(_visible("v" * 120, 90), "…" + "v" * 83)
        self.assertEqual(_visible("v" * 120, 8), "…v")

    def test_protocols_are_held_and_restored_around_the_interface(self):
        stream = TtyStream()
        with patch("sys.stdout", stream), tui_protocols():
            stream.write("run")
        self.assertEqual(
            stream.getvalue(), ENABLE_PROTOCOLS + "run" + RESTORE_PROTOCOLS
        )
        stream = TtyStream()
        with (
            patch("sys.stdout", stream),
            self.assertRaises(ValueError),tui_protocols()
        ):
            raise ValueError
        self.assertEqual(stream.getvalue(), ENABLE_PROTOCOLS + RESTORE_PROTOCOLS)

    def test_protocols_are_skipped_for_redirected_output(self):
        stream = io.StringIO()
        with patch("sys.stdout", stream), tui_protocols():
            pass
        self.assertEqual(stream.getvalue(), "")

    def test_external_reasserts_protocols_after_each_suspension(self):
        ui = test_tui.TerminalTests().terminal([])
        stream = TtyStream()
        with (
            patch("sys.stdout", stream),
            patch("brig.ui.tui.terminal.curses.def_prog_mode"),
            patch("brig.ui.tui.terminal.curses.endwin"),
            patch("brig.ui.tui.terminal.curses.reset_prog_mode"),
        ):
            self.assertEqual(ui.external(lambda: "done"), "done")
        self.assertEqual(stream.getvalue(), RESTORE_PROTOCOLS + ENABLE_PROTOCOLS)
