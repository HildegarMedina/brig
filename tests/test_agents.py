"""Extensible agent selection, installation and persisted profile snapshots."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from brig.agents import AGENTS, validate_agents
from brig.application import Application
from brig.dockerfile import render_dockerfile
from brig.engine import DemoEngine
from brig.errors import BrigError
from brig.models import ProfileRevision
from brig.profile_yaml import profile_path
from brig.storage import JsonStateStore
from brig.tui import InteractiveApp
from tests.fakes import FakeVersionCatalog
from tests.test_tui import ScriptedTerminal


class AgentTests(unittest.TestCase):
    def test_invalid_agent_lists_have_clear_errors(self):
        for agents, default, error in (
            ([], "claude", "at least one agent"),
            (["claude", "claude"], "claude", "only once"),
            (["claude"], "codex", "default agent"),
            (["unknown"], "unknown", "Unknown agent"),
            (["codex"], "codex", "future integration"),
            ("claude", "claude", "at least one agent"),
        ):
            with self.subTest(agents=agents), self.assertRaisesRegex(BrigError, error):
                validate_agents(agents, default)

    def test_legacy_profiles_keep_their_agent_and_immutable_yaml(self):
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStateStore(Path(folder))
            app = Application(store, DemoEngine(), FakeVersionCatalog)
            # Simulate a schema-1 revision from before the agent list existed.
            app.save_profile("legacy", {"python": "3.12.8"}, {}, {})
            app.state.profiles[0].revisions[0].agents = None
            document = profile_path(Path(folder), "legacy", 1)
            document.unlink()
            store.save(app.state)
            original = document.read_bytes()
            loaded = store.load()
            self.assertEqual(loaded.profiles[0].latest.selected_agents, ["claude"])
            store.save(loaded)
            self.assertEqual(document.read_bytes(), original)

    def test_multi_agent_wizard_and_installation_follow_registry_and_snapshot(self):
        # A future adapter becomes selectable by supplying its own installation.
        codex = replace(
            AGENTS["codex"],
            stage=("FROM debian:bookworm-slim AS codex_binary", ""),
            image=("COPY --from=codex_binary /codex /usr/local/bin/codex", ""),
        )
        with tempfile.TemporaryDirectory() as folder, patch.dict(AGENTS, codex=codex):
            store = JsonStateStore(Path(folder) / "data")
            app = Application(store, DemoEngine(), FakeVersionCatalog)
            terminal = ScriptedTerminal(
                inputs=["both-agents"],
                multiples=[["python"], [], [], ["claude", "codex"]],
                choices=[0, 1],
            )
            InteractiveApp(app, terminal, Path(folder) / "data").profile_wizard()
            revision = app.profile("both-agents").latest
            self.assertEqual(revision.selected_agents, ["claude", "codex"])
            self.assertEqual(revision.agent, "codex")
            self.assertEqual(store.load(), app.state)
            contents = profile_path(Path(folder) / "data", "both-agents", 1).read_text()
            self.assertIn('agents:\n  - "claude"\n  - "codex"', contents)
            project = app.create_project("both-project", Path(folder), "both-agents")
            self.assertIn("AS claude_binary", render_dockerfile(project))
            self.assertIn("AS codex_binary", render_dockerfile(project))
            app.save_profile(
                "both-agents",
                {"python": "3.12.8"},
                {},
                {},
                agent="codex",
                agents=["codex"],
                editing=True,
            )
            self.assertEqual(project.configuration.selected_agents, ["claude", "codex"])
            single = app.create_project(
                "codex-project", Path(folder) / "data", "both-agents"
            )
            self.assertNotIn("AS claude_binary", render_dockerfile(single))
            with self.assertRaisesRegex(BrigError, "not selected"):
                app.run_agent("codex-project", "claude")
            self.assertFalse(app.project("codex-project").running)

    def test_corrupt_stored_agent_selection_is_rejected(self):
        from brig.storage import _revision
        from dataclasses import asdict

        raw = asdict(ProfileRevision(1, {"python": "3.12.8"}, {}, {}, agents=[]))
        with self.assertRaisesRegex(BrigError, "at least one agent"):
            _revision(raw)
