"""Runtime range boundaries and live per-release requirements."""

import json
import unittest
from unittest.mock import Mock

from brig.components.compatibility import ReleaseInfo, matches
from brig.components.versions import LiveVersionCatalog
from tests.fakes import published_images


class RequirementTests(unittest.TestCase):
    def test_npm_union_and_patch_boundaries(self):
        requirement = "^18.17.0 || >=20.0.0"
        for runtime, expected in (
            ("18.16.9", False),
            ("18.17.0", True),
            ("19.0.0", False),
            ("20.0.0", True),
            ("22.1.0", True),
        ):
            with self.subTest(runtime=runtime):
                self.assertEqual(matches(requirement, runtime, "npm"), expected)

    def test_npm_caret_tilde_wildcard_and_hyphen_ranges(self):
        cases = (
            ("^0.2.3", "0.3.0", False),
            ("~20.1.0", "20.2.0", False),
            ("20.x", "20.5.2", True),
            ("18.0.0 - 20.0.0", "20.0.1", False),
        )
        for spec, runtime, expected in cases:
            with self.subTest(spec=spec):
                self.assertEqual(matches(spec, runtime, "npm"), expected)

    def test_python_upper_bounds_exclusions_and_compatible_release(self):
        for spec, runtime, expected in (
            (">=3.9,<3.13", "3.13.0", False),
            (">=3.9,!=3.10.*", "3.10.9", False),
            ("~=3.11.0", "3.11.11", True),
            ("~=3.11.0", "3.12.0", False),
        ):
            with self.subTest(spec=spec, runtime=runtime):
                self.assertEqual(matches(spec, runtime, "python"), expected)

    def test_missing_and_unknown_constraints_never_assume_compatibility(self):
        for info in (
            ReleaseInfo(),
            ReleaseInfo(requirements=("nonsense",), dialect="npm"),
            ReleaseInfo(requirements=(">=3.9",), dialect="unknown"),
        ):
            with self.subTest(info=info):
                self.assertFalse(info.supports("3.12.0"))


class LiveCompatibilityTests(unittest.TestCase):
    def test_npm_filters_each_release_using_its_own_node_engine(self):
        payload = {
            "versions": {
                "12.0.0": {
                    "dist": {"tarball": "url"},
                    "engines": {"node": "^24.5.0 || >=26.0.0"},
                },
                "10.0.0": {
                    "dist": {"tarball": "url"},
                    "engines": {"node": "^18.17.0 || >=20.0.0"},
                },
                "9.0.0": {"dist": {"tarball": "url"}},
                "8.0.0": {
                    "dist": {"tarball": "url"},
                    "engines": {"node": "unsupported"},
                },
            }
        }
        fetch = Mock(return_value=json.dumps(payload))
        catalog = LiveVersionCatalog(published_images(fetch))
        self.assertEqual(
            catalog.compatible_versions("npm", {"node": "22.13.1"}), ("10.0.0",)
        )
        issue = catalog.compatibility_issue("npm", "12.0.0", {"node": "22.13.1"})
        self.assertIn("Node.js 22.13.1", issue)
        self.assertIn("^24.5.0", issue)
        self.assertIn(
            "not published",
            catalog.compatibility_issue("npm", "9.0.0", {"node": "22.13.1"}),
        )
        self.assertEqual(fetch.call_count, 1)

    def test_python_file_requirements_and_yanked_files_are_respected(self):
        payload = {
            "releases": {
                "26.0.0": [{"requires_python": ">=3.13"}],
                "25.0.0": [
                    {"requires_python": ">=3.9,<3.13"},
                    {"requires_python": ">=3.13", "yanked": True},
                ],
                "24.0.0": [{"requires_python": ">=3.8"}, {"requires_python": ">=3.13"}],
                "23.0.0": [{}],
            }
        }
        catalog = LiveVersionCatalog(published_images(lambda url: json.dumps(payload)))
        self.assertEqual(
            catalog.compatible_versions("pip", {"python": "3.12.8"}),
            ("25.0.0", "24.0.0"),
        )
        self.assertEqual(
            catalog.compatible_versions("pip", {"python": "3.13.1"}),
            ("26.0.0", "24.0.0"),
        )

    def test_composer_minimum_php_and_lts_use_official_release_metadata(self):
        payload = {
            "stable": [
                {"version": "2.10.3", "min-php": 80400, "lts": False},
                {"version": "2.2.30", "min-php": 50300, "lts": True},
                {"version": "1.10.28", "min-php": 50300, "eol": True},
            ]
        }
        catalog = LiveVersionCatalog(published_images(lambda url: json.dumps(payload)))
        self.assertEqual(catalog.versions("composer"), ("2.10.3", "2.2.30"))
        self.assertEqual(
            catalog.compatible_versions("composer", {"php": "8.3.15"}), ("2.2.30",)
        )
        self.assertEqual(
            catalog.compatible_versions("composer", {"php": "8.4.0"}),
            ("2.10.3", "2.2.30"),
        )
        self.assertEqual(catalog.label("composer", "2.2.30"), "2.2.30 · LTS")

    def test_composer_missing_minimum_php_is_not_selectable(self):
        payload = {"stable": [{"version": "2.10.3", "lts": False}]}
        catalog = LiveVersionCatalog(published_images(lambda url: json.dumps(payload)))
        self.assertEqual(catalog.compatible_versions("composer", {"php": "8.4.0"}), ())

    def test_node_labels_are_dynamic_and_default_prefers_lts(self):
        responses = {
            "https://raw.githubusercontent.com/docker-library/official-images/master/library/node": "Tags: 26.1.0, 24.2.0\nArchitectures: amd64",
            "https://nodejs.org/dist/index.json": json.dumps(
                [
                    {"version": "v26.1.0", "lts": False},
                    {"version": "v24.2.0", "lts": "Krypton"},
                ]
            ),
        }
        fetch = Mock(side_effect=lambda url: responses[url])
        catalog = LiveVersionCatalog(published_images(fetch))
        versions = list(catalog.versions("node"))
        self.assertEqual(catalog.label("node", "26.1.0"), "26.1.0 · Current")
        self.assertEqual(catalog.label("node", "24.2.0"), "24.2.0 · LTS")
        self.assertEqual(catalog.preferred_version("node", versions), "24.2.0")
        self.assertEqual(fetch.call_count, 2)

    def test_mysql_innovation_and_multiple_lts_branches_are_not_hardcoded(self):
        responses = {
            "https://raw.githubusercontent.com/docker-library/official-images/master/library/mysql": "Tags: 28.7.1, 11.7.2, 8.4.12\nArchitectures: amd64",
            "https://raw.githubusercontent.com/docker-library/mysql/master/versions.json": json.dumps(
                {
                    "innovation": {"version": "28.7.1"},
                    "11.7": {"version": "11.7.2"},
                    "8.4": {"version": "8.4.12"},
                }
            ),
        }
        catalog = LiveVersionCatalog(published_images(lambda url: responses[url]))
        versions = list(catalog.versions("mysql"))
        self.assertEqual(catalog.label("mysql", "28.7.1"), "28.7.1 · Innovation")
        self.assertEqual(catalog.label("mysql", "8.4.12"), "8.4.12 · LTS")
        self.assertEqual(catalog.preferred_version("mysql", versions), "11.7.2")

    def test_missing_channel_metadata_does_not_invent_lts_label(self):
        catalog = LiveVersionCatalog(
            published_images(
                lambda url: (
                    "{}"
                    if url.endswith("versions.json")
                    else "Tags: 30.1.0\nArchitectures: amd64"
                )
            )
        )
        self.assertEqual(
            catalog.label("mysql", "30.1.0"), "30.1.0 · Channel unverified"
        )


class JavaReleaseTests(unittest.TestCase):
    library = "https://raw.githubusercontent.com/docker-library/official-images/master/library/"

    def catalog(self, manifests, unpublished=()):
        responses = {self.library + name: text for name, text in manifests.items()}
        responses["https://api.adoptium.net/v3/info/available_releases"] = json.dumps(
            {"available_lts_releases": [17, 21, 25]}
        )
        return LiveVersionCatalog(
            published_images(lambda url: responses[url], unpublished)
        )

    def test_java_offers_majors_with_jdk_images_and_prefers_adoptium_lts(self):
        catalog = self.catalog(
            {
                "eclipse-temurin": "Tags: 27.0.1_9-jdk, 27-jdk, 27\nArchitectures: amd64\n\n"
                "Tags: 25.0.3_5-jdk, 25-jdk, 25, 21-jdk, 21, 20-jre, 20\n"
                "Architectures: amd64\n"
            }
        )
        versions = list(catalog.versions("java"))
        self.assertEqual(versions, ["27", "25", "21"])
        self.assertEqual(catalog.label("java", "27"), "27 · Stable")
        self.assertEqual(catalog.label("java", "21"), "21 · LTS")
        self.assertEqual(catalog.preferred_version("java", versions), "25")

    def test_maven_and_gradle_support_only_published_jdk_pairings(self):
        catalog = self.catalog(
            {
                "maven": "Tags: 3.10.0-eclipse-temurin-8, 3.10.0-eclipse-temurin-21, 3.10.0\n"
                "Architectures: amd64\n\n"
                "Tags: 4.0.0-rc-7-eclipse-temurin-21, 4.0.0-rc-7\nArchitectures: amd64\n",
                "gradle": "Tags: 9.8.1-jdk21, 9.8.1-jdk25, 9.8.1, jdk21\n"
                "Architectures: amd64\n\n"
                "Tags: 8.14.6-jdk8, 8.14.6-jdk21, 8.14.6\nArchitectures: amd64\n",
            }
        )
        self.assertEqual(catalog.versions("maven"), ("3.10.0",))
        self.assertEqual(
            catalog.compatible_versions("gradle", {"java": "8"}), ("8.14.6",)
        )
        self.assertEqual(
            catalog.compatible_versions("gradle", {"java": "21"}), ("9.8.1", "8.14.6")
        )
        self.assertEqual(catalog.compatible_versions("maven", {"java": "25"}), ())
        self.assertIn(
            "Requires: 21 OR 25",
            catalog.compatibility_issue("gradle", "9.8.1", {"java": "8"}),
        )

    def test_java_tool_images_must_be_pushed_for_the_selected_jdk(self):
        catalog = self.catalog(
            {
                "maven": "Tags: 3.10.0-eclipse-temurin-21, 3.10.0-eclipse-temurin-25, 3.10.0\n"
                "Architectures: amd64\n"
            },
            unpublished=("/maven/tags/3.10.0-eclipse-temurin-25",),
        )
        self.assertEqual(
            catalog.compatible_versions("maven", {"java": "21"}), ("3.10.0",)
        )
        self.assertEqual(catalog.compatible_versions("maven", {"java": "25"}), ())
        self.assertIn(
            "not yet published for Java (Eclipse Temurin) 25 on Docker Hub "
            "(maven:3.10.0-eclipse-temurin-25)",
            catalog.compatibility_issue("maven", "3.10.0", {"java": "25"}),
        )

    def test_exact_requirements_never_match_partially(self):
        self.assertTrue(matches("21", "21", "exact"))
        self.assertFalse(matches("21", "2", "exact"))
