"""Language selection, portable catalogs, translated flows and unchanged data."""

import argparse
import ast
import io
import json
import os
import tempfile
import unittest
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from string import Formatter
from unittest.mock import Mock, patch

from brig.application import Application
from brig.docker.dockerfile import render_dockerfile
from brig.errors import BrigError
from brig.i18n import (
    catalog,
    current_language,
    normalize_language,
    reset_language,
    resolve_language,
    set_language,
    tr,
)
from brig.i18n.preferences import load_language, save_language
from brig.persistence.profile_yaml import render_profile
from brig.ui.cli import main
from brig.ui.listings import list_rows
from brig.ui.presentation import configuration_lines, project_lines
from brig.ui.tui.profiles import ProfileViews
from tests import test_dashboard
from tests.demo_engine import DemoEngine
from tests.fakes import FakeVersionCatalog, MemoryStore, demo_state
from tests.test_tui import ScriptedTerminal


class I18nTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        token = set_language("en")
        self.addCleanup(reset_language, token)
        environment = patch.dict(os.environ, {"LANG": "C.UTF-8"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def cli(self, *args):
        with (
            patch("sys.stdout", new_callable=io.StringIO) as output,
            patch("sys.stderr", new_callable=io.StringIO) as errors,
        ):
            result = main(["--data-dir", str(self.root), *args])
        return result, output.getvalue(), errors.getvalue()

    def test_locale_normalization_and_priority(self):
        for value, expected in (
            ("en_US.UTF-8", "en"),
            ("es-MX", "es"),
            ("PT_br.utf8", "pt"),
            (" Español ", None),
            ("C", None),
            ("", None),
        ):
            self.assertEqual(normalize_language(value), expected)
        self.assertEqual(resolve_language(), "en")
        with patch.dict(os.environ, {"LANG": "pt_BR.UTF-8"}):
            self.assertEqual(resolve_language(), "pt")
            self.assertEqual(resolve_language(saved="es"), "es")
            with patch.dict(
                os.environ, {"BRIG_LANG": "en", "LC_MESSAGES": "es_ES.UTF-8"}
            ):
                self.assertEqual(resolve_language(saved="pt"), "en")
                self.assertEqual(resolve_language("es", "pt"), "es")
            with patch.dict(os.environ, {"LC_MESSAGES": "es_ES.UTF-8"}):
                self.assertEqual(resolve_language(), "es")
            with patch.dict(
                os.environ, {"LC_ALL": "fr_FR.UTF-8", "BRIG_LANG": "unknown"}
            ):
                self.assertEqual(resolve_language(), "en")

    def test_translation_context_and_english_fallback(self):
        for code, label in (
            ("en", "Projects"),
            ("es", "Proyectos"),
            ("pt", "Projetos"),
        ):
            token = set_language(code)
            self.assertEqual(tr("Projects"), label)
            self.assertEqual(tr("Unknown template"), "Unknown template")
            reset_language(token)
        self.assertEqual(current_language(), "en")
        with self.assertRaisesRegex(ValueError, "Unsupported language"):
            set_language("de")
        self.assertEqual(catalog("en"), {})

    def test_catalogs_cover_templates_and_preserve_format_fields(self):
        messages = set()
        for path in Path("src/brig").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "tr"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    messages.add(node.args[0].value)
        formatter = Formatter()
        for code in ("es", "pt"):
            translated = catalog(code)
            self.assertTrue(messages.issubset(translated), messages - translated.keys())
            for message, text in translated.items():
                with self.subTest(code=code, message=message):
                    self.assertTrue(isinstance(text, str) and text)
                    original = sorted(
                        (field, spec, conversion)
                        for _, field, spec, conversion in formatter.parse(message)
                        if field is not None
                    )
                    localized = sorted(
                        (field, spec, conversion)
                        for _, field, spec, conversion in formatter.parse(text)
                        if field is not None
                    )
                    self.assertEqual(original, localized)
                    # argparse uses percent-format mappings, not brace fields.
                    values = {
                        "argument_name": "--lang",
                        "message": "error",
                        "value": "bad",
                        "choices": "en, es, pt",
                        "type": "int",
                        "prog": "brig",
                    }
                    if "%(" in message:
                        self.assertEqual(text.count("%("), message.count("%("))
                        text % values
            self.assertEqual(
                json.loads(
                    files("brig.i18n").joinpath("catalogs", f"{code}.json").read_text()
                ),
                translated,
            )

    def test_preference_roundtrip_auto_and_separate_definitions(self):
        self.assertIsNone(load_language(self.root))
        for code in ("es", "pt", "en", "auto"):
            save_language(self.root, code)
            self.assertEqual(load_language(self.root), None if code == "auto" else code)
        self.assertEqual(list(self.root.iterdir()), [self.root / "preferences.json"])
        with self.assertRaisesRegex(BrigError, "Unsupported language"):
            save_language(self.root, "de")

    def test_preference_read_errors_are_actionable(self):
        path = self.root / "preferences.json"
        for contents in (
            "{",
            "[]",
            '{"language": "de"}',
            '{"language": []}',
            '{"language": "en", "extra": true}',
            b"\xff",
        ):
            path.write_bytes(
                contents if isinstance(contents, bytes) else contents.encode()
            )
            with (
                self.subTest(contents=contents),
                self.assertRaisesRegex(BrigError, "Cannot read language preferences"),
            ):
                load_language(self.root)
        with (
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            self.assertRaisesRegex(BrigError, "denied"),
        ):
            load_language(self.root)

    def test_failed_preference_save_preserves_previous_file_and_cleans_temporary(self):
        save_language(self.root, "en")
        before = (self.root / "preferences.json").read_bytes()
        with (
            patch(
                "brig.i18n.preferences.os.replace", side_effect=OSError("disk failure")
            ),
            self.assertRaisesRegex(BrigError, "Cannot save language"),
        ):
            save_language(self.root, "es")
        self.assertEqual((self.root / "preferences.json").read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.root / "preferences.json"])
        with (
            patch.object(Path, "mkdir", side_effect=PermissionError("denied")),
            self.assertRaisesRegex(BrigError, "denied"),
        ):
            save_language(self.root, "pt")

    def test_cli_saves_language_without_docker_or_project_state(self):
        with (
            patch("brig.ui.cli.Application") as app,
            patch("brig.ui.cli.DockerEngine") as engine,
        ):
            result, output, _ = self.cli("language", "es")
            self.assertEqual(result, 0)
            self.assertIn("Preferencia de idioma guardada: Español", output)
            self.assertIn("Idioma: Español (es)", self.cli("language")[1])
            self.assertIn("Automatic", self.cli("language", "auto")[1])
            app.assert_not_called()
            engine.assert_not_called()
        self.assertFalse((self.root / "state.json").exists())
        self.assertEqual(current_language(), "en")

    def test_cli_explicit_override_environment_and_saved_language(self):
        save_language(self.root, "es")
        with patch("brig.ui.cli.DockerEngine"):
            self.assertIn("No hay perfiles", self.cli("profile", "list")[1])
            with patch.dict(os.environ, {"BRIG_LANG": "pt"}):
                self.assertIn("Não há perfis", self.cli("profile", "list")[1])
                self.assertIn(
                    "No profiles", self.cli("--lang", "en", "profile", "list")[1]
                )
            self.assertEqual(load_language(self.root), "es")
            self.assertIn(
                "Preferencia de idioma", self.cli("--lang", "es", "language", "pt")[1]
            )
            self.assertEqual(load_language(self.root), "pt")

    def test_cli_help_and_argument_errors_are_translated_and_restore_argparse(self):
        original = argparse._
        for code, heading in (("es", "opciones:"), ("pt", "opções:")):
            with (
                patch("sys.stdout", new_callable=io.StringIO) as output,
                self.assertRaises(SystemExit) as error,
            ):
                main(["--data-dir", str(self.root), "--lang", code, "--help"])
            self.assertEqual(error.exception.code, 0)
            self.assertIn(heading, output.getvalue())
            self.assertIn("profile", output.getvalue())
            with (
                patch("sys.stderr", new_callable=io.StringIO) as output,
                self.assertRaises(SystemExit) as error,
            ):
                main(
                    ["--data-dir", str(self.root), "--lang", code, "profile", "import"]
                )
            self.assertEqual(error.exception.code, 2)
            self.assertIn(
                "obligatorios" if code == "es" else "obrigatórios", output.getvalue()
            )
            self.assertIs(argparse._, original)
            self.assertEqual(current_language(), "en")

    def test_missing_global_argument_uses_selected_language(self):
        for args in (["--lang", "es", "--data-dir"], ["--lang", "pt", "--lang"]):
            with (
                patch("sys.stderr", new_callable=io.StringIO) as output,
                self.assertRaises(SystemExit) as error,
            ):
                main(args)
            self.assertEqual(error.exception.code, 2)
            self.assertIn(
                "se esperaba" if "es" in args else "era esperado", output.getvalue()
            )
        self.assertEqual(current_language(), "en")

    def test_cli_corrupt_preferences_can_be_replaced_with_explicit_language(self):
        (self.root / "preferences.json").write_text("bad")
        result, _, error = self.cli("language")
        self.assertEqual(result, 1)
        self.assertIn("Cannot read language preferences", error)
        self.assertEqual(self.cli("--lang", "es", "language", "es")[0], 0)
        self.assertEqual(load_language(self.root), "es")

    def test_bootstrap_leaves_executed_program_arguments_untouched(self):
        fake = Mock()
        fake.shell.return_value = ""
        fake.resolve_project.return_value.name = "api"
        fake.resolve_project.return_value.configuration.selected_agents = ["claude"]
        fake.resolve_project.return_value.configuration.agent = "claude"
        with (
            patch("brig.ui.cli.Application", return_value=fake),
            patch("brig.ui.cli.DockerEngine"),
        ):
            self.assertEqual(
                self.cli(
                    "run",
                    "api",
                    "--command",
                    "python",
                    "--lang",
                    "pt",
                    "--data-dir",
                    "/not-brig",
                )[0],
                0,
            )
        fake.shell.assert_called_once_with(
            "api", ["python", "--lang", "pt", "--data-dir", "/not-brig"], agent="claude"
        )

    def test_cli_backend_error_is_translated(self):
        result, _, error = self.cli("--lang", "pt", "project", "show", "missing")
        self.assertEqual(result, 1)
        self.assertIn("Projeto desconhecido: missing", error)

    def test_translated_summaries_preserve_identifiers_and_internal_status(self):
        app = Application(MemoryStore(demo_state()), DemoEngine(), FakeVersionCatalog)
        project = app.state.projects[0]
        for code, name, version, stopped in (
            ("es", "Proyecto", "Versión", "detenido"),
            ("pt", "Projeto", "Versão", "parado"),
        ):
            set_language(code)
            lines = project_lines(app, project)
            self.assertTrue(any(line.startswith(name) for line in lines))
            self.assertTrue(
                any(
                    line.startswith(version)
                    for line in configuration_lines(project.configuration)
                )
            )
            self.assertTrue(any(stopped in line for line in lines))
            self.assertIn("web_dev", list_rows(app, "project")[0])
            self.assertEqual(app.project_status(project), "stopped")
        project.path = None
        self.assertIn("sem pasta montada", project_lines(app, project)[1])

    def test_language_does_not_change_yaml_dockerfile_or_project_snapshots(self):
        state = demo_state()
        original = deepcopy(state)
        version = state.profiles[0].latest
        yaml = render_profile("web_dev", version)
        dockerfile = render_dockerfile(state.projects[0])
        for code in ("es", "pt"):
            set_language(code)
            self.assertEqual(render_profile("web_dev", version), yaml)
            self.assertEqual(render_dockerfile(state.projects[0]), dockerfile)
        self.assertEqual(state, original)

    def test_profile_wizard_translates_labels_and_keeps_saved_component_keys(self):
        for code, title, prefix in (
            ("es", "Crear perfil", "Lenguajes"),
            ("pt", "Criar perfil", "Ambientes"),
        ):
            set_language(code)
            app = Application(MemoryStore(None), DemoEngine(), FakeVersionCatalog)
            terminal = ScriptedTerminal(
                inputs=[f"test-{code}"],
                multiples=[
                    [f"{tr('Runtimes')} · Python"],
                    [f"{tr('Python package managers')} · uv"],
                    [],
                    ["codex"],
                ],
                choices=[0, 0],
            )
            with patch.object(terminal, "confirm", return_value=True) as confirm:
                ProfileViews(app, terminal, self.root).profile_wizard()
            self.assertTrue(confirm.call_args.args[0].startswith(title))
            self.assertTrue(
                any(
                    option.startswith(prefix)
                    for _, options, _ in terminal.selections
                    for option in options
                )
            )
            self.assertEqual(
                app.profile(f"test-{code}").latest.runtimes, {"python": "3.12.8"}
            )
            self.assertEqual(
                app.profile(f"test-{code}").latest.selected_agents, ["codex"]
            )

    def test_dashboard_language_selection_persists_and_renders_immediately(self):
        dashboard = test_dashboard.DashboardTests().dashboard([])
        dashboard.directory = self.root
        with patch.object(dashboard.ui, "choose", return_value=2):
            dashboard.open("Settings", dashboard.items("Settings")[0], False)
        self.assertEqual(load_language(self.root), "es")
        self.assertEqual(current_language(), "es")
        settings = dashboard.items("Settings")[0]
        self.assertIn("Idioma     Español", settings.details)
        with patch.object(dashboard.ui, "choose", return_value=0):
            dashboard.open("Settings", settings, False)
        self.assertIsNone(load_language(self.root))
        self.assertEqual(current_language(), "en")
        set_language("pt")
        with patch.object(dashboard.ui, "key", return_value="\x1b"):
            dashboard.run()
        self.assertTrue(any("Projetos" in line for line in dashboard.ui.screen.written))
        self.assertTrue(any("parado" in line for line in dashboard.ui.screen.written))

    def test_translated_dashboard_preserves_start_stop_shortcut(self):
        dashboard = test_dashboard.DashboardTests().dashboard(["s", "s", "\x1b"])
        set_language("es")
        with patch.object(
            dashboard.ui, "external", side_effect=lambda action: action()
        ):
            dashboard.run()
        self.assertFalse(dashboard.app.project("website").running)
        self.assertTrue(
            any("en ejecución" in line for line in dashboard.ui.screen.written)
        )
