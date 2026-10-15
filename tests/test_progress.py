"""Terminal compatibility, lifecycle cleanup and hidden subprocess diagnostics."""

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from brig.docker.client import DockerClient
from brig.errors import BrigError
from brig.progress import _animate, output_options, progress, verbose_output
from brig.ui.cli import _main, parser


class Terminal(io.StringIO):
    def __init__(self, encoding="utf-8", tty=True):
        super().__init__()
        self.codec = encoding
        self.tty = tty

    @property
    def encoding(self):
        return self.codec

    def isatty(self):
        return self.tty


class ProgressTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_animation_advances_and_stops_without_sleeping(self):
        stop = Mock()
        stop.wait.side_effect = [False, False, True]
        render = Mock()
        _animate(stop, render, "abc")
        self.assertEqual([call.args[0] for call in render.call_args_list], ["b", "c"])
        stop.wait.assert_called_with(0.09)

    def test_static_output_for_pipes_ci_and_unsupported_terminals(self):
        for tty, environment in (
            (False, {}),
            (True, {"TERM": "dumb"}),
            (True, {"CI": "1"}),
            (True, {"BRIG_NO_ANIMATION": "1"}),
        ):
            stream = Terminal(tty=tty)
            with (
                patch.dict(os.environ, environment),
                redirect_stderr(stream),
                progress("Preparing environment…"),
            ):
                stream.write("work\n")
            self.assertEqual(stream.getvalue(), "  Preparing environment…\nwork\n")

    def test_unicode_animation_color_and_cleanup(self):
        stream = Terminal()
        with (
            redirect_stderr(stream),
            patch("brig.progress.Thread") as thread,
            patch("brig.progress.Event") as event,
            patch(
                "brig.progress.shutil.get_terminal_size",
                return_value=os.terminal_size((32, 24)),
            ),
        ):
            with progress("Starting project…"):
                self.assertIn("⠋", stream.getvalue())
            event.return_value.set.assert_called_once()
            thread.return_value.start.assert_called_once()
            thread.return_value.join.assert_called_once()
        value = stream.getvalue()
        self.assertIn("\033[36m", value)
        self.assertIn("✓ Starting project…", value)
        self.assertTrue(value.endswith("\n"))

    def test_ascii_no_color_narrow_terminal_and_interrupt(self):
        stream = Terminal(encoding="ascii")
        with (
            redirect_stderr(stream),
            patch.dict(os.environ, {"NO_COLOR": ""}),
            patch("brig.progress.Thread") as thread,
            patch(
                "brig.progress.shutil.get_terminal_size",
                return_value=os.terminal_size((12, 24)),
            ),
        ):
            with progress("Build…"):
                pass
            self.assertIn("+ Build?", stream.getvalue())
            with self.assertRaises(KeyboardInterrupt), progress("Stop…"):
                raise KeyboardInterrupt
            self.assertEqual(thread.return_value.join.call_count, 2)
        self.assertIn("! Stop?", stream.getvalue())
        self.assertNotIn("\033", stream.getvalue())
        self.assertLessEqual(max(map(len, stream.getvalue().split("\r"))), 11)

    def test_verbosity_flags_are_scoped_to_invocation(self):
        self.assertFalse(verbose_output())
        for args in (["--verbose", "up"], ["run", "--verbose"], ["down", "--verbose"]):
            self.assertTrue(parser().parse_args(args).verbose)
            with patch(
                "brig.ui.cli._execute", side_effect=lambda args: verbose_output()
            ):
                self.assertTrue(_main(args))
            self.assertFalse(verbose_output())
        with self.assertRaises(RuntimeError), output_options(verbose=True):
            self.assertTrue(verbose_output())
            raise RuntimeError
        self.assertFalse(verbose_output())

    def client(self, script):
        def runner(args, **options):
            return subprocess.run([sys.executable, "-c", script], **options)

        return DockerClient(runner)

    def test_successful_output_is_hidden_and_does_not_pollute_stdout(self):
        client = self.client(
            "import sys; print('build detail'); print('pull detail', file=sys.stderr)"
        )
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stderr(errors), redirect_stdout(output):
            result = client.run(["compose", "build"], capture=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "  Preparing environment…\n")

    def test_failure_includes_bounded_combined_diagnostics(self):
        client = self.client(
            "import sys; print('x' * 80000); print('actual failure', file=sys.stderr); sys.exit(7)"
        )
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(BrigError) as error:
                client.run(["compose", "build"], capture=False, status="Building…")
            self.assertIn("actual failure", str(error.exception))
            self.assertIn("exit 7", str(error.exception))
            self.assertLess(len(str(error.exception)), 66000)
            result = client.run(["compose", "build"], capture=False, check=False)
        self.assertIn("actual failure", result.stderr)

    def test_verbose_streams_to_stderr_and_capture_still_returns_data(self):
        def runner(args, **options):
            options["stdout"].write("live detail\n")
            self.assertIs(options["stderr"], options["stdout"])
            return subprocess.CompletedProcess(args, 0)

        errors = io.StringIO()
        with output_options(verbose=True), redirect_stderr(errors):
            DockerClient(runner).run(["compose", "build"], capture=False)
            result = self.client("print('inspection')").run(["inspect"])
        self.assertEqual(errors.getvalue(), "live detail\n")
        self.assertEqual(result.stdout, "inspection\n")

    def test_interrupted_build_stops_indicator_and_closes_output(self):
        captured = []

        def runner(args, **options):
            captured.append(options["stdout"])
            raise KeyboardInterrupt

        with redirect_stderr(Terminal()), patch("brig.progress.Thread") as thread:
            with self.assertRaises(KeyboardInterrupt):
                DockerClient(runner).run(["compose", "build"], capture=False)
            thread.return_value.join.assert_called_once()
        self.assertTrue(captured[0].closed)
