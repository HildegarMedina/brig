"""Transport, corrupted storage and Docker failures preserve explicit boundaries."""

import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

from brig.components.agents import AGENTS
from brig.components.providers import MAX_RESPONSE_BYTES, fetch_text
from brig.components.versions import LiveVersionCatalog
from brig.docker.client import DockerClient
from brig.docker.compose import compose_definition
from brig.docker.dockerfile import render_dockerfile
from brig.docker.workspace import DockerWorkspace
from brig.errors import BrigError
from brig.persistence.codec import _revision, decode_state
from brig.persistence.profile_yaml import profile_path
from brig.persistence.store import JsonStateStore
from tests import test_docker_engine
from tests.fakes import demo_state


class BoundaryTests(unittest.TestCase):
    def fixture(self):
        case = test_docker_engine.DockerEngineTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_http_request_uses_provider_headers_timeout_and_size_limit(self):
        for url, accept in (
            ("https://registry.npmjs.org/npm", "application/vnd.npm.install-v1+json"),
            ("https://pypi.org/pypi/pip/json", "application/json, text/plain"),
        ):
            response = Mock()
            response.read.return_value = "versión".encode()
            with patch("brig.components.providers.urlopen") as open_url:
                open_url.return_value.__enter__.return_value = response
                self.assertEqual(fetch_text(url), "versión")
                self.assertEqual(open_url.call_args.kwargs["timeout"], 10)
                self.assertEqual(
                    open_url.call_args.args[0].get_header("Accept"), accept
                )
                response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)
        with patch("brig.components.providers.urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = b"x" * (
                MAX_RESPONSE_BYTES + 1
            )
            with self.assertRaisesRegex(ValueError, "too large"):
                fetch_text("https://example.test/versions")

    def test_runtime_has_no_tool_compatibility_requirement(self):
        catalog = LiveVersionCatalog(
            Mock(side_effect=AssertionError("unexpected fetch"))
        )
        self.assertIsNone(catalog.compatibility_issue("python", "3.12.8", {}))

    def test_docker_execution_and_inspection_errors_are_explicit(self):
        for error, message in (
            (FileNotFoundError(), "not installed"),
            (OSError("denied"), "Cannot execute"),
        ):
            client = DockerClient(Mock(side_effect=error))
            with self.assertRaisesRegex(BrigError, message):
                client.run(["version"])
        case = self.fixture()
        client = case.engine.client
        client._checked = True
        for output, code, message in (
            ("", 1, "Cannot inspect"),
            ("[]", 0, "invalid container"),
        ):
            with (
                patch.object(
                    client,
                    "run",
                    return_value=CompletedProcess(
                        [], code, output, "permission denied"
                    ),
                ),
                self.assertRaisesRegex(BrigError, message),
            ):
                client.inspect(case.project)

    def test_docker_compose_plugin_failure_has_actionable_error(self):
        client = DockerClient(
            Mock(
                side_effect=[
                    CompletedProcess([], 0, "27", ""),
                    CompletedProcess([], 1, "", "unavailable"),
                ]
            )
        )
        with self.assertRaisesRegex(BrigError, "Compose is unavailable"):
            client.check()

    def test_volume_failures_do_not_reinitialize_storage(self):
        case = self.fixture()
        volumes = case.engine.volumes
        for output, code, message in (
            ("", 1, "Cannot inspect project data"),
            ("[]", 0, "invalid data volume"),
            ('[{"Labels": {}}]', 0, "not managed"),
        ):
            with patch.object(
                volumes.client,
                "run",
                return_value=CompletedProcess([], code, output, "denied"),
            ) as run:
                with self.assertRaisesRegex(BrigError, message):
                    volumes.check_data_versions(case.project)
                self.assertFalse(
                    any("create" in call.args[0] for call in run.call_args_list)
                )
        for output, code, message in (
            ("", 1, "Cannot inspect shared"),
            ("[]", 0, "invalid shared"),
        ):
            with (
                patch.object(
                    volumes.client,
                    "run",
                    return_value=CompletedProcess([], code, output, "denied"),
                ),
                self.assertRaisesRegex(BrigError, message),
            ):
                volumes.ensure_agent_volumes(case.project)

    def test_agents_without_configuration_do_not_mount_or_create_shared_storage(self):
        case = self.fixture()
        with patch.dict(
            AGENTS, claude=replace(AGENTS["claude"], config_directory=None)
        ):
            with patch.object(case.engine.client, "run") as run:
                case.engine.volumes.ensure_agent_volumes(case.project)
            run.assert_not_called()
            definition = compose_definition(case.project, "test", 1234, 4321)
            self.assertNotIn("claude_config", definition["volumes"])

    def test_credentials_reject_malformed_passwords_without_replacement(self):
        case = self.fixture()
        path = (
            case.engine.workspace.project_directory(case.project) / "credentials.json"
        )
        path.parent.mkdir(parents=True)
        contents = '{"postgresql":{"password":"short","root_password":"short"}}'
        path.write_text(contents)
        with self.assertRaisesRegex(BrigError, "Restore credentials"):
            case.engine.credentials.load(case.project)
        self.assertEqual(path.read_text(), contents)

    def test_image_inspection_and_failed_start_never_mark_project_running(self):
        case = self.fixture()
        original = case.engine.client.run

        def fail_image(args, **kwargs):
            if args[:2] == ["image", "inspect"]:
                return CompletedProcess(args, 1, "", "denied")
            return original(args, **kwargs)

        with (
            patch.object(case.engine.client, "run", side_effect=fail_image),
            self.assertRaisesRegex(BrigError, "Cannot inspect project image"),
        ):
            case.start()
        with (
            patch.object(case.engine, "is_running", return_value=False),
            self.assertRaisesRegex(BrigError, "not running"),
        ):
            case.start()
        self.assertFalse(case.app.project("api").running)

    def test_stopped_container_uses_saved_compose_and_validates_ownership(self):
        case = self.fixture()
        self.assertIn("already stopped", case.engine.stop(case.project))
        case.engine.prepare(case.project)
        self.assertIn("Stopped", case.engine.stop(case.project))
        with (
            patch.object(
                case.engine.client, "inspect", return_value={"Config": {"Labels": {}}}
            ),
            self.assertRaisesRegex(BrigError, "managed Compose"),
        ):
            case.engine.stop(case.project)

    def test_shell_errors_propagate_without_running_unselected_agents(self):
        case = self.fixture()
        with self.assertRaisesRegex(BrigError, "container is stopped"):
            case.engine.shell(case.project, ["python", "--version"])
        with self.assertRaisesRegex(BrigError, "not selected"):
            case.engine.run_agent(case.project, "codex")
        with patch.object(
            case.engine.client, "inspect", return_value={"State": {"Running": True}}
        ):
            for result, message in (
                (OSError("denied"), "Cannot enter"),
                (CompletedProcess([], 9), "status 9"),
            ):
                with (
                    patch.object(
                        case.engine.client,
                        "runner",
                        side_effect=result if isinstance(result, OSError) else None,
                        return_value=result,
                    ),
                    self.assertRaisesRegex(BrigError, message),
                ):
                    case.engine.shell(case.project, ["python", "--version"])

    def test_workspace_write_and_lock_failures_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = DockerWorkspace(Path(folder))
            with (
                patch("brig.docker.workspace.os.open", side_effect=OSError("denied")),
                self.assertRaisesRegex(BrigError, "Cannot lock"),
                workspace.lock(demo_state().projects[0]),
            ):
                self.fail("lock must fail")
            with (
                patch(
                    "brig.docker.workspace.os.replace", side_effect=OSError("denied")
                ),
                self.assertRaisesRegex(BrigError, "Cannot write"),
            ):
                workspace.write(Path(folder) / "config", "data")
            self.assertEqual(list(Path(folder).glob("tmp*")), [])

    def test_dockerfile_rejects_invalid_versions_and_missing_runtime_builders(self):
        project = demo_state().projects[0]
        project.configuration.number = 0
        with self.assertRaisesRegex(BrigError, "invalid profile revision"):
            render_dockerfile(project)
        project.configuration.number = 1
        with (
            patch.dict("brig.docker.dockerfile.RUNTIME_IMAGES", {}, clear=True),
            self.assertRaisesRegex(BrigError, "No Dockerfile builder"),
        ):
            render_dockerfile(project)

    def test_corrupt_state_records_are_rejected(self):
        state = {"schema_version": 1, **asdict(demo_state())}
        changes = [
            (lambda raw: raw.update(schema_version=999), "schema version"),
            (
                lambda raw: raw["profiles"][1].update(name=raw["profiles"][0]["name"]),
                "Duplicate names",
            ),
            (lambda raw: raw["profiles"][0].update(extra=1), "profile fields"),
            (lambda raw: raw["projects"][0].update(extra=1), "project fields"),
            (lambda raw: raw["projects"][0].update(id=""), "project ID"),
            (lambda raw: raw["projects"][0].update(running="yes"), "project status"),
            (lambda raw: raw["projects"][0].update(path="relative"), "project path"),
            (
                lambda raw: raw["projects"][1].update(id=raw["projects"][0]["id"]),
                "project IDs",
            ),
            (
                lambda raw: [p.update(path="/same") for p in raw["projects"]],
                "project paths",
            ),
            (
                lambda raw: raw["projects"][0].update(profile="missing"),
                "unknown profile",
            ),
        ]
        for change, message in changes:
            raw = deepcopy(state)
            change(raw)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValueError, message),
            ):
                decode_state(raw)
        for field, value, message in (
            ("number", 0, "revision number"),
            ("tools", [], "version mapping"),
        ):
            raw = asdict(demo_state().profiles[0].latest)
            raw[field] = value
            with self.assertRaisesRegex(ValueError, message):
                _revision(raw)

    def test_storage_read_errors_and_modified_yaml_preserve_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStateStore(Path(folder))
            with (
                patch.object(Path, "read_text", side_effect=OSError("denied")),
                self.assertRaisesRegex(BrigError, "Cannot read"),
            ):
                store.load()
            state = demo_state()
            store.save(state)
            document = profile_path(Path(folder), state.profiles[0].name, 1)
            document.write_text("modified")
            with self.assertRaisesRegex(BrigError, "modified"):
                store.save(state)
            self.assertEqual(document.read_text(), "modified")

    def test_profile_deletion_filesystem_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStateStore(Path(folder))
            state = demo_state()
            store.save(state)
            with (
                patch(
                    "brig.persistence.store.tempfile.mkdtemp",
                    side_effect=OSError("denied"),
                ),
                self.assertRaisesRegex(BrigError, "Cannot delete profile"),
            ):
                store.delete_profile(state, state.profiles[0])
            self.assertTrue(
                profile_path(Path(folder), state.profiles[0].name, 1).exists()
            )
