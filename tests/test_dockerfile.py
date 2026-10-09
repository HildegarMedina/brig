"""Pinned image generation, driver selection, and non-destructive exports."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from brig.application import Application
from brig.dockerfile import render_dockerfile, write_dockerfile
from brig.engine import DemoEngine
from brig.errors import BrigError
from brig.models import ProfileRevision, Project, State
from tests.fakes import FakeVersionCatalog, MemoryStore


def php_project(services=None):
    return Project(
        "project-id",
        "laravel_project",
        None,
        "laravel",
        ProfileRevision(1, {"php": "8.3.15"}, {"composer": "2.8.5"}, services or {}),
    )


class DockerfileTests(unittest.TestCase):
    def test_exact_images_nonroot_user_and_runtime_workspace(self):
        contents = render_dockerfile(php_project({"mysql": "8.4.3"}))
        self.assertIn("FROM php:8.3.15-cli-bookworm\n", contents)
        self.assertIn("FROM composer:2.8.5 AS composer_binary\n", contents)
        self.assertIn(
            "COPY --from=composer_binary /usr/bin/composer /usr/local/bin/composer",
            contents,
        )
        self.assertIn("WORKDIR /workspace\nUSER brig", contents)
        self.assertIn("ARG BRIG_UID=1000", contents)
        self.assertIn("ARG BRIG_GID=1000", contents)
        self.assertNotIn("latest", contents)
        self.assertEqual(
            [line for line in contents.splitlines() if line.startswith("COPY")],
            ["COPY --from=composer_binary /usr/bin/composer /usr/local/bin/composer"],
        )
        self.assertNotIn("composer install", contents)

    def test_database_driver_dependencies_and_deduplication(self):
        contents = render_dockerfile(
            php_project({"mysql": "8.4.3", "mariadb": "11.4.4", "postgresql": "17.2"})
        )
        extension_line = next(
            line for line in contents.splitlines() if "docker-php-ext-install" in line
        )
        self.assertEqual(extension_line.count("pdo_mysql"), 1)
        self.assertIn("pdo_pgsql", extension_line)
        self.assertIn("libpq-dev", contents)
        without_databases = render_dockerfile(php_project())
        self.assertNotIn("pdo_mysql", without_databases)
        self.assertNotIn("pdo_pgsql", without_databases)
        self.assertNotIn("libpq-dev", without_databases)

    def test_composer_is_optional_and_services_are_not_embedded(self):
        project = php_project({"redis": "7.4.2"})
        project.configuration.tools = {}
        contents = render_dockerfile(project)
        self.assertNotIn("FROM composer:", contents)
        self.assertNotIn("COPY --from=", contents)
        self.assertNotIn("redis-server", contents)
        self.assertNotIn("mysql-server", contents)

    def test_runtime_combinations_and_optional_tools(self):
        for runtimes, tools in (
            ({"python": "3.12.8"}, {}),
            ({"node": "22.13.1"}, {}),
            ({"php": "8.3.15", "node": "22.13.1"}, {"composer": "2.8.5"}),
            ({"php": "8.3.15", "python": "3.12.8"}, {"pip": "24.3.1"}),
            (
                {"python": "3.12.8", "node": "22.13.1"},
                {"uv": "0.6.0", "pnpm": "10.0.0"},
            ),
            (
                {"php": "8.3.15", "python": "3.12.8", "node": "22.13.1"},
                {
                    "composer": "2.8.5",
                    "pip": "24.3.1",
                    "npm": "10.9.2",
                    "yarn": "1.22.22",
                },
            ),
        ):
            project = php_project()
            project.configuration.runtimes = runtimes
            project.configuration.tools = tools
            with self.subTest(runtimes=runtimes):
                contents = render_dockerfile(project)
                for runtime, version in runtimes.items():
                    self.assertIn(f"{runtime}:{version}", contents)
                for tool in ("composer", "uv", "pnpm", "yarn", "npm", "pip"):
                    if tool in tools:
                        self.assertIn(tools[tool], contents)
                if "php" not in runtimes:
                    self.assertNotIn("docker-php-ext-install", contents)
                    self.assertNotIn("FROM php:", contents)
                if "composer" not in tools:
                    self.assertNotIn("FROM composer:", contents)
                if "python" in runtimes and "php" in runtimes:
                    self.assertIn("/brig-python-packages", contents)
                    self.assertIn("/opt/python/", contents)
                if "node" in runtimes:
                    self.assertIn("ENV NPM_CONFIG_PREFIX=/opt/node", contents)

    def test_tool_order_and_generation_are_deterministic(self):
        project = php_project()
        project.configuration.runtimes = {"node": "22.13.1"}
        project.configuration.tools = {
            "yarn": "1.22.22",
            "pnpm": "10.0.0",
            "npm": "10.9.2",
        }
        contents = render_dockerfile(project)
        self.assertLess(contents.index("npm@10.9.2"), contents.index("pnpm@10.0.0"))
        self.assertLess(contents.index("pnpm@10.0.0"), contents.index("yarn@1.22.22"))
        project.configuration.tools = dict(
            reversed(list(project.configuration.tools.items()))
        )
        self.assertEqual(render_dockerfile(project), contents)

    def test_invalid_version_cannot_inject_dockerfile_instructions(self):
        project = php_project()
        project.configuration.runtimes["php"] = "8.3.15\nRUN touch /tmp/injected"
        with self.assertRaises(BrigError):
            render_dockerfile(project)

    def test_project_uses_its_snapshot_after_profile_edit_without_network_or_state_changes(
        self,
    ):
        with tempfile.TemporaryDirectory() as folder:
            app = Application(MemoryStore(State()), DemoEngine(), FakeVersionCatalog)
            app.save_profile("laravel", {"php": "8.3.15"}, {"composer": "2.8.5"}, {})
            project = app.create_project("laravel_project", Path(folder), "laravel")
            app.save_profile("laravel", {"php": "8.2.27"}, {}, {}, editing=True)
            before = deepcopy(app.state)
            with patch(
                "brig.versions.urlopen",
                side_effect=AssertionError("No network during generation"),
            ):
                contents = app.project_dockerfile(None, Path(folder) / "subfolder")
            self.assertIn("FROM php:8.3.15-cli-bookworm", contents)
            self.assertIn("FROM composer:2.8.5", contents)
            self.assertNotIn("8.2.27", contents)
            self.assertEqual(app.state, before)
            self.assertFalse(project.running)

    def test_export_writes_complete_file_and_refuses_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / ".brig" / "Dockerfile"
            contents = render_dockerfile(php_project())
            self.assertEqual(write_dockerfile(destination, contents), destination)
            self.assertEqual(destination.read_text(), contents)
            with self.assertRaisesRegex(BrigError, "already exists"):
                write_dockerfile(destination, "different")
            self.assertEqual(destination.read_text(), contents)
            self.assertEqual(list(destination.parent.glob("*.tmp")), [])

    def test_failed_export_and_race_preserve_existing_files_and_clean_temporaries(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "Dockerfile"

            def raced_link(source, target):
                destination.write_text("user-owned Dockerfile")
                raise FileExistsError("created concurrently")

            with (
                patch("brig.dockerfile.os.link", side_effect=raced_link),
                self.assertRaisesRegex(BrigError, "already exists"),
            ):
                write_dockerfile(destination, "generated")
            self.assertEqual(destination.read_text(), "user-owned Dockerfile")
            with (
                patch("brig.dockerfile.os.fsync", side_effect=OSError("write failure")),
                self.assertRaisesRegex(BrigError, "Cannot export"),
            ):
                write_dockerfile(Path(folder) / "other", "generated")
            self.assertFalse((Path(folder) / "other").exists())
            self.assertEqual(list(Path(folder).glob(".brig-dockerfile-*.tmp")), [])
