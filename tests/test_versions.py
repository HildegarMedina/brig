"""Release parsing and fresh operation snapshots without external requests."""

import json
import unittest
from unittest.mock import Mock
from urllib.error import URLError

from brig.errors import BrigError
from brig.versions import LiveVersionCatalog


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
            LiveVersionCatalog(fetch).versions("python"), ("3.10.2", "3.9.9")
        )

    def test_postgres_two_part_versions_exclude_major_alias(self):
        fetch = Mock(
            return_value="Tags: 17.2, 17, latest, 16.6\nArchitectures: amd64\n"
        )
        self.assertEqual(
            LiveVersionCatalog(fetch).versions("postgresql"), ("17.2", "16.6")
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
            LiveVersionCatalog(lambda url: json.dumps(data)).versions("uv"),
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
            LiveVersionCatalog(lambda url: json.dumps(data)).versions("pnpm"),
            ("9.2.0",),
        )

    def test_snapshot_fetches_once_and_next_operation_refreshes(self):
        fetch = Mock(
            side_effect=[
                "Tags: 8.3.1\nArchitectures: amd64",
                "Tags: 8.3.2\nArchitectures: amd64",
            ]
        )
        first = LiveVersionCatalog(fetch)
        self.assertEqual(first.versions("php"), ("8.3.1",))
        self.assertEqual(first.versions("php"), ("8.3.1",))
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(LiveVersionCatalog(fetch).versions("php"), ("8.3.2",))

    def test_yarn_classic_excludes_modern_releases_from_npm(self):
        data = {
            "versions": {
                version: {"dist": {"tarball": "url"}}
                for version in ("1.22.22", "2.4.3")
            }
        }
        self.assertEqual(
            LiveVersionCatalog(lambda url: json.dumps(data)).versions("yarn"),
            ("1.22.22",),
        )

    def test_failure_has_no_fallback_and_can_be_retried(self):
        fetch = Mock(
            side_effect=[URLError("offline"), "Tags: 8.3.1\nArchitectures: amd64"]
        )
        catalog = LiveVersionCatalog(fetch)
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
                LiveVersionCatalog(lambda url: text).versions(name)
