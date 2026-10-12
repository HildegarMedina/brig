"""Extensible agent selection, installation and persisted profile snapshots."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from brig.application import Application
from brig.components.agents import AGENTS, validate_agents
from brig.docker.compose import compose_definition
from brig.docker.dockerfile import render_dockerfile
from brig.errors import BrigError
from brig.models import ProfileVersion
from brig.persistence.profile_yaml import profile_path
from brig.persistence.store import JsonStateStore
from brig.ui.tui import InteractiveApp
from tests.demo_engine import DemoEngine
from tests.fakes import FakeVersionCatalog
from tests.test_tui import ScriptedTerminal


class AgentTests(unittest.TestCase):
    def test_invalid_agent_lists_have_clear_errors(self):
        for agents, default, error in (
            ([], "claude", "at least one agent"),
            (["claude", "claude"], "claude", "only once"),
            (["claude"], "codex", "default agent"),
            (["unknown"], "unknown", "Unknown agent"),
            ([None], "claude", "Unknown agent"),
            ("claude", "claude", "at least one agent"),
        ):
            with self.subTest(agents=agents), self.assertRaisesRegex(BrigError, error):
                validate_agents(agents, default)

    def test_legacy_profiles_keep_their_agent_and_immutable_yaml(self):
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStateStore(Path(folder))
            app = Application(store, DemoEngine(), FakeVersionCatalog)
            # Simulate a schema-1 version from before the agent list existed.
            app.save_profile("legacy", {"python": "3.12.8"}, {}, {})
            app.state.profiles[0].versions[0].agents = None
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
            version = app.profile("both-agents").latest
            self.assertEqual(version.selected_agents, ["claude", "codex"])
            self.assertEqual(version.agent, "codex")
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
        from dataclasses import asdict

        from brig.persistence.codec import decode_profile_version

        raw = asdict(ProfileVersion(1, {"python": "3.12.8"}, {}, {}, agents=[]))
        with self.assertRaisesRegex(BrigError, "at least one agent"):
            decode_profile_version(raw)

    def test_native_adapters_only_install_selected_agents_for_each_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            for runtime, version in (
                ("php", "8.3.15"),
                ("python", "3.12.8"),
                ("node", "22.13.1"),
            ):
                for selected in ("codex", "opencode"):
                    with self.subTest(runtime=runtime, agent=selected):
                        app = Application(
                            JsonStateStore(Path(folder)),
                            DemoEngine(),
                            FakeVersionCatalog,
                        )
                        name = f"{runtime}-{selected}"
                        app.save_profile(
                            name,
                            {runtime: version},
                            {},
                            {},
                            agent=selected,
                            agents=[selected],
                        )
                        source = Path(folder) / name
                        source.mkdir()
                        project = app.create_project(name, source, name)
                        dockerfile = render_dockerfile(project)
                        self.assertIn(f"AS {selected}_binary", dockerfile)
                        for other in set(AGENTS) - {selected}:
                            self.assertNotIn(f"AS {other}_binary", dockerfile)
                        definition = compose_definition(
                            project, "brig-test", 1000, 1000
                        )
                        mounts = definition["services"][f"agent_{selected}"]["volumes"]
                        for directory in AGENTS[selected].history_directories:
                            target = f"{AGENTS[selected].config_directory}/{directory}"
                            self.assertTrue(
                                any(
                                    mount.get("target") == target
                                    for mount in mounts
                                    if isinstance(mount, dict)
                                )
                            )

    def test_container_launchers_enable_full_permissions_and_forward_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            binary = directory / "agent-stub"
            binary.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "print(json.dumps({'args': sys.argv[1:], "
                "'permission': os.environ.get('OPENCODE_PERMISSION')}))\n"
            )
            binary.chmod(0o755)
            for agent, integration in AGENTS.items():
                with self.subTest(agent=agent):
                    instruction = next(
                        line
                        for line in integration.image
                        if f" > /usr/local/bin/{agent} " in line
                    )
                    arguments = shlex.split(instruction.removeprefix("RUN "))
                    script = "\n".join(arguments[2 : arguments.index(">")]) + "\n"
                    executable = shlex.split(
                        next(
                            line
                            for line in script.splitlines()
                            if line.startswith("exec ")
                        )
                    )[1]
                    script = script.replace(executable, shlex.quote(str(binary)))
                    script = script.replace(
                        "/home/brig/.local/state", str(directory / "state")
                    )
                    launcher = directory / f"{agent}-launcher"
                    launcher.write_text(script)
                    environment = dict(os.environ, OPENCODE_PERMISSION='{"*":"ask"}')
                    result = subprocess.run(
                        ["/bin/sh", str(launcher), "--example", "literal ; $HOME"],
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=True,
                    )
                    observed = json.loads(result.stdout)
                    self.assertEqual(
                        observed["args"][-2:], ["--example", "literal ; $HOME"]
                    )
                    if agent == "claude":
                        self.assertIn(
                            "--dangerously-skip-permissions", observed["args"]
                        )
                        settings_index = observed["args"].index("--settings") + 1
                        self.assertEqual(
                            json.loads(observed["args"][settings_index]),
                            {"skipDangerousModePermissionPrompt": True},
                        )
                    elif agent == "codex":
                        self.assertIn(
                            "--dangerously-bypass-approvals-and-sandbox",
                            observed["args"],
                        )
                        self.assertIn(
                            'cli_auth_credentials_store="file"', observed["args"]
                        )
                    else:
                        self.assertIn("--auto", observed["args"])
                        self.assertEqual(
                            json.loads(observed["permission"]), {"*": "allow"}
                        )

    def test_unimplemented_registry_adapter_remains_unavailable(self):
        future = replace(AGENTS["codex"], stage=(), image=())
        with (
            patch.dict(AGENTS, future=future),
            self.assertRaisesRegex(BrigError, "future integration"),
        ):
            validate_agents(["future"], "future")
