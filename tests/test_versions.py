"""Release parsing and fresh operation snapshots without external requests."""

import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from brig.components.providers import image_published
from brig.components.versions import LiveVersionCatalog
from brig.errors import BrigError
from tests.fakes import published_images


class VersionTests(unittest.TestCase):
    def test_docker_exact_versions_are_sorted_deduplicated_and_linux_only(self):
        fetch = Mock(
            return_value="""Tags: 3.9.9, 3.9, latest, 3.10.2-slim, 3.11.0rc1
SharedTags: 3.10.2, 3.9.9
Architectures: amd64, arm64v8

Tags: 3.12.1
Architectures: windows-amd64
"""
        )
        self.assertEqual(
            LiveVersionCatalog(published_images(fetch)).versions("python"),
            ("3.10.2", "3.9.9"),
        )

    def test_debian_runtimes_require_a_bookworm_image_for_each_release(self):
        fetch = Mock(
            return_value="""Tags: 1.28.0-trixie, 1.28.0
Architectures: amd64

Tags: 1.27.2-bookworm, 1.27.2-trixie, 1.27.2
Architectures: amd64
"""
        )
        self.assertEqual(
            LiveVersionCatalog(published_images(fetch)).versions("go"), ("1.27.2",)
        )

    def test_postgres_two_part_versions_exclude_major_alias(self):
        fetch = Mock(
            return_value="Tags: 17.2, 17, latest, 16.6\nArchitectures: amd64\n"
        )
        self.assertEqual(
            LiveVersionCatalog(published_images(fetch)).versions("postgresql"),
            ("17.2", "16.6"),
        )

    def test_pypi_excludes_yanked_empty_and_prerelease_versions(self):
        data = {
            "releases": {
                "1.2.0": [{"yanked": False}],
                "1.3.0": [{"yanked": True}],
                "1.4.0": [],
                "2.0.0rc1": [{}],
                "1.1.0": [{"yanked": True}, {"yanked": False}],
            }
        }
        self.assertEqual(
            LiveVersionCatalog(published_images(lambda url: json.dumps(data))).versions(
                "uv"
            ),
            ("1.2.0", "1.1.0"),
        )

    def test_npm_excludes_deprecated_unpublished_and_prerelease_versions(self):
        data = {
            "versions": {
                "9.2.0": {"dist": {"tarball": "https://example.com/package.tgz"}},
                "9.3.0": {"deprecated": "removed", "dist": {"tarball": "url"}},
                "9.4.0": {},
                "10.0.0-beta.1": {"dist": {"tarball": "url"}},
            }
        }
        self.assertEqual(
            LiveVersionCatalog(published_images(lambda url: json.dumps(data))).versions(
                "pnpm"
            ),
            ("9.2.0",),
        )

    def test_snapshot_fetches_once_and_next_operation_refreshes(self):
        fetch = Mock(
            side_effect=[
                "Tags: 8.3.1\nArchitectures: amd64",
                "Tags: 8.3.2\nArchitectures: amd64",
            ]
        )
        first = LiveVersionCatalog(published_images(fetch))
        self.assertEqual(first.versions("php"), ("8.3.1",))
        self.assertEqual(first.versions("php"), ("8.3.1",))
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(
            LiveVersionCatalog(published_images(fetch)).versions("php"), ("8.3.2",)
        )

    def test_yarn_classic_excludes_modern_releases_from_npm(self):
        data = {
            "versions": {
                version: {"dist": {"tarball": "url"}}
                for version in ("1.22.22", "2.4.3")
            }
        }
        self.assertEqual(
            LiveVersionCatalog(published_images(lambda url: json.dumps(data))).versions(
                "yarn"
            ),
            ("1.22.22",),
        )

    def test_failure_has_no_fallback_and_can_be_retried(self):
        fetch = Mock(
            side_effect=[URLError("offline"), "Tags: 8.3.1\nArchitectures: amd64"]
        )
        catalog = LiveVersionCatalog(published_images(fetch))
        with self.assertRaisesRegex(BrigError, "Cannot fetch.*PHP"):
            catalog.versions("php")
        self.assertEqual(catalog.versions("php"), ("8.3.1",))

    def test_malformed_or_empty_responses_are_actionable(self):
        for name, text in (
            ("uv", "{broken"),
            ("npm", "{}"),
            ("php", "Tags: latest\nArchitectures: amd64"),
            ("uv", '{"releases": null}'),
        ):
            with (
                self.subTest(name=name, text=text),
                self.assertRaisesRegex(BrigError, "Cannot fetch"),
            ):
                LiveVersionCatalog(
                    published_images(lambda url, text=text: text)
                ).versions(name)


class PublishedImageTests(unittest.TestCase):
    manifest = (
        "Tags: 3.15.0-bookworm, 3.15.0, 3.15\nArchitectures: amd64\n\n"
        "Tags: 3.14.8-bookworm, 3.14.8\nArchitectures: amd64\n"
    )

    def test_releases_whose_image_is_not_pushed_yet_are_not_offered(self):
        # The manifest lists a release hours before its image can be pulled.
        requested = []
        source = published_images(
            lambda url: self.manifest, unpublished=("/python/tags/3.15.0-bookworm",)
        )
        catalog = LiveVersionCatalog(lambda url: requested.append(url) or source(url))
        self.assertEqual(catalog.versions("python"), ("3.14.8",))
        self.assertIn(
            "https://hub.docker.com/v2/namespaces/library/repositories/python"
            "/tags/3.15.0-bookworm",
            requested,
        )
        self.assertTrue(catalog.published("python:3.14.8-bookworm"))
        self.assertEqual(len(requested), 3)

    def test_no_published_release_is_reported_without_fallback(self):
        source = published_images(lambda url: self.manifest, unpublished=("-bookworm",))
        with self.assertRaisesRegex(BrigError, "with published images"):
            LiveVersionCatalog(source).versions("python")

    def test_images_must_be_linux_and_built_for_this_architecture(self):
        text = json.dumps(
            {
                "images": [
                    {"architecture": "amd64", "os": "linux"},
                    {"architecture": "arm64", "os": "windows"},
                    {"architecture": "riscv64", "os": "linux", "status": "inactive"},
                ]
            }
        )
        self.assertTrue(image_published(text, "amd64"))
        self.assertTrue(image_published(text, None))
        self.assertFalse(image_published(text, "arm64"))
        self.assertFalse(image_published(text, "riscv64"))
        self.assertFalse(image_published("{}", None))

    def test_unverifiable_images_ask_to_retry(self):
        for error in (
            HTTPError("url", 500, "Server Error", None, None),
            URLError("offline"),
        ):

            def fetch(url, error=error):
                if url.startswith("https://hub.docker.com/"):
                    raise error
                return self.manifest

            with (
                self.subTest(error=error),
                self.assertRaisesRegex(
                    BrigError, "Cannot verify the python:3.1.*-bookworm image"
                ),
            ):
                LiveVersionCatalog(fetch).versions("python")

    def test_kafka_releases_come_from_apache_docker_hub_tags(self):
        tags = json.dumps(
            {
                "results": [
                    {"name": name}
                    for name in ("latest", "4.3.2-rc3", "4.3.1", "3.9.0", "4.0")
                ]
            }
        )
        requested = []

        def fetch(url):
            requested.append(url)
            return tags

        catalog = LiveVersionCatalog(published_images(fetch))
        self.assertEqual(catalog.versions("kafka"), ("4.3.1", "3.9.0"))
        self.assertTrue(
            requested[0].startswith(
                "https://hub.docker.com/v2/repositories/apache/kafka/tags?"
            )
        )
        self.assertEqual(catalog.label("kafka", "4.3.1"), "4.3.1 · Stable")

    def test_rabbitmq_requires_its_management_image(self):
        manifest = (
            "Tags: 4.3.6, 4.3.6-management\nArchitectures: amd64\n\n"
            "Tags: 4.4.0\nArchitectures: amd64\n"
        )
        catalog = LiveVersionCatalog(published_images(lambda url: manifest))
        self.assertEqual(catalog.versions("rabbitmq"), ("4.3.6",))
        self.assertTrue(catalog.published("rabbitmq:4.3.6-management"))
