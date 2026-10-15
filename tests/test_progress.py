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
from brig.progress import (
    _animate,
    _ship_frame,
    output_options,
    progress,
    verbose_output,
)
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
        _animate(stop, render)
        self.assertEqual([call.args[0] for call in render.call_args_list], [1, 2])
        stop.wait.assert_called_with(0.16)

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
                return_value=os.terminal_size((80, 24)),
            ),
        ):
            with progress("Starting project…"):
                self.assertIn(r"/_|_\/_|_\ ", stream.getvalue())
                self.assertIn("\033[6A", stream.getvalue())
                render = thread.call_args.kwargs["args"][1]
                render(2)
            event.return_value.set.assert_called_once()
            thread.return_value.start.assert_called_once()
            thread.return_value.join.assert_called_once()
        value = stream.getvalue()
        self.assertIn("\033[36m", value)
        self.assertIn("✓ Starting project…", value)
        self.assertTrue(value.endswith("\n"))
        self.assertIn("\033[2K", value)
        self.assertNotIn("\\", value.split("\033[2K")[-1])

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

    def test_sailing_ship_has_two_masts_and_moving_waves(self):
        first, next_frame = _ship_frame(0), _ship_frame(2)
        self.assertEqual(first[0].count("|"), 2)
        self.assertEqual(
            [row.strip() for row in first[:-1]],
            [row.strip() for row in next_frame[:-1]],
        )
        self.assertNotEqual(first[0], next_frame[0])
        self.assertNotEqual(first[-1], next_frame[-1])
        self.assertTrue(all(len(row) <= 28 for row in first))
        self.assertTrue("".join(first).isascii())

    def test_sinking_ship_descends_once_and_stays_submerged(self):
        frames = [_ship_frame(index, sinking=True) for index in (0, 2, 4, 6, 8)]
        self.assertEqual(len({len(frame) for frame in frames}), 1)
        for depth, frame in enumerate(frames):
            self.assertEqual(frame[: min(depth, 3)], ("",) * min(depth, 3))
            self.assertIn("~", frame[-1])
        self.assertIn("_", frames[0][-2])
        for index in (8, 10, 20, 100):
            self.assertNotIn("|", "".join(_ship_frame(index, sinking=True)))
            self.assertNotIn("_", "".join(_ship_frame(index, sinking=True)))
        self.assertNotEqual(frames[-1], _ship_frame(10, sinking=True))
        compact_start = _ship_frame(0, sinking=True, compact=True)[0]
        compact_end = _ship_frame(100, sinking=True, compact=True)[0]
        self.assertEqual(compact_start.count("|"), 2)
        self.assertNotIn("|", compact_end)
        self.assertIn("~", compact_end)

    def test_short_terminal_uses_compact_ship_and_keeps_status_visible(self):
        stream = Terminal()
        with (
            redirect_stderr(stream),
            patch("brig.progress.Thread"),
            patch(
                "brig.progress.shutil.get_terminal_size",
                return_value=os.terminal_size((80, 6)),
            ),
            progress("Starting…"),
        ):
            self.assertIn("Starting…", stream.getvalue())
            self.assertIn(r"|\|\__/", stream.getvalue())
        self.assertNotIn("\033[6A", stream.getvalue())

    def test_multiline_failure_clears_ship_and_respects_no_color(self):
        stream = Terminal(encoding="ascii")
        with (
            redirect_stderr(stream),
            patch.dict(os.environ, {"NO_COLOR": "1"}),
            patch("brig.progress.Thread") as thread,
            patch(
                "brig.progress.shutil.get_terminal_size",
                return_value=os.terminal_size((80, 24)),
            ),
        ):
            with (
                self.assertRaisesRegex(RuntimeError, "failure"),
                progress("Stopping…", animation="sinking"),
            ):
                render = thread.call_args.kwargs["args"][1]
                render(4)
                raise RuntimeError("failure")
            thread.return_value.join.assert_called_once()
        self.assertIn("! Stopping?", stream.getvalue())
        self.assertIn("\033[2K", stream.getvalue())
        self.assertNotIn("\033[36m", stream.getvalue())
        self.assertTrue(stream.getvalue().isascii())

    def test_engine_uses_sailing_for_build_and_start_and_sinking_for_down(self):
        from tests.test_docker_engine import DockerEngineTests

        case = DockerEngineTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        with patch("brig.docker.client.progress") as indicator:
            case.start()
            self.assertEqual(indicator.call_count, 2)
            for call in indicator.call_args_list:
                self.assertEqual(call.kwargs["animation"], "sailing")
            case.app.stop("api")
            self.assertEqual(indicator.call_args.kwargs["animation"], "sinking")

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
            "import sys; print('x' * 80000, flush=True); print('actual failure', file=sys.stderr); sys.exit(7)"
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
