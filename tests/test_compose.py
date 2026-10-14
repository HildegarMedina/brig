"""Project isolation, service initialization and generated Compose contracts."""

import tempfile
import unittest
from pathlib import Path

from brig.docker.compose import compose_definition, render_compose
from brig.docker.services import service_environment
from brig.errors import BrigError
from tests.test_dockerfile import php_project


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.project = php_project(
            {
                "postgresql": "18.6",
                "mysql": "8.4.3",
                "mariadb": "11.4.4",
                "mongodb": "8.0.4",
                "redis": "7.4.2",
                "rabbitmq": "4.3.6",
                "kafka": "4.3.1",
            }
        )
        self.project.path = self.folder.name

    def test_services_have_pinned_images_healthchecks_and_persistent_private_data(self):
        definition = compose_definition(self.project, "brig-test:version", 1234, 4321)
        dev = definition["services"]["dev"]
        self.assertEqual(dev["build"]["args"], {"BRIG_UID": "1234", "BRIG_GID": "4321"})
        self.assertEqual(dev["volumes"][0]["source"], self.project.path)
        self.assertEqual(dev["volumes"][0]["bind"], {"create_host_path": False})
        self.assertTrue(dev["init"])
        for name, version in self.project.configuration.services.items():
            service = definition["services"][name]
            self.assertIn(f":{version}", service["image"])
            self.assertNotIn("ports", service)
            self.assertEqual(dev["depends_on"][name], {"condition": "service_healthy"})
            self.assertIn("healthcheck", service)
            self.assertIn("volumes", service)
        self.assertEqual(
            definition["services"]["postgresql"]["volumes"],
            ["postgresql_data:/var/lib/postgresql"],
        )
        self.assertEqual(
            definition["services"]["redis"]["command"],
            ["redis-server", "--appendonly", "yes"],
        )
        self.assertEqual(len(definition["services"]["mongodb"]["volumes"]), 2)
        rabbitmq = definition["services"]["rabbitmq"]
        self.assertEqual(rabbitmq["image"], "rabbitmq:4.3.6-management")
        # A stable node name keeps RabbitMQ's data when the container is recreated.
        self.assertEqual(rabbitmq["hostname"], "rabbitmq")
        self.assertEqual(rabbitmq["volumes"], ["rabbitmq_data:/var/lib/rabbitmq"])
        kafka = definition["services"]["kafka"]
        self.assertEqual(kafka["image"], "apache/kafka:4.3.1")
        self.assertEqual(kafka["volumes"], ["kafka_data:/var/lib/kafka/data"])
        self.assertEqual(kafka["healthcheck"]["timeout"], "30s")

    def test_versions_with_different_image_layouts(self):
        self.project.configuration.services = {
            "postgresql": "17.2",
            "mongodb": "4.4.29",
        }
        definition = compose_definition(self.project, "image:test", 1000, 1000)
        self.assertEqual(
            definition["services"]["postgresql"]["volumes"],
            ["postgresql_data:/var/lib/postgresql/data"],
        )
        self.assertEqual(
            definition["services"]["mongodb"]["healthcheck"]["test"][1], "mongo"
        )

    def test_environment_connections_match_initialization_without_exposing_root_mysql(
        self,
    ):
        for name in (
            "postgresql",
            "mysql",
            "mariadb",
            "mongodb",
            "redis",
            "rabbitmq",
            "kafka",
        ):
            with self.subTest(service=name):
                initialization, developer = service_environment(
                    name, "application-secret", "root-secret"
                )
                self.assertNotIn("root-secret", developer.values())
                if name == "postgresql":
                    self.assertEqual(
                        initialization["POSTGRES_PASSWORD"], developer["PGPASSWORD"]
                    )
                if name in ("mysql", "mariadb"):
                    prefix = name.upper()
                    self.assertEqual(
                        initialization[f"{prefix}_PASSWORD"],
                        developer[f"{prefix}_PASSWORD"],
                    )
                    self.assertEqual(developer[f"{prefix}_HOST"], name)
                if name == "mongodb":
                    self.assertIn(
                        "application-secret@mongodb:27017", developer["MONGODB_URI"]
                    )
                if name == "rabbitmq":
                    self.assertEqual(
                        initialization["RABBITMQ_DEFAULT_PASS"],
                        developer["RABBITMQ_PASSWORD"],
                    )
                    self.assertEqual(
                        developer["AMQP_URL"],
                        "amqp://brig:application-secret@rabbitmq:5672/",
                    )
                if name == "kafka":
                    # Clients must be told the broker's name on the private network.
                    self.assertEqual(
                        initialization["KAFKA_ADVERTISED_LISTENERS"],
                        "PLAINTEXT://kafka:9092",
                    )
                    self.assertEqual(
                        initialization["KAFKA_LOG_DIRS"], "/var/lib/kafka/data"
                    )
                    self.assertEqual(developer["KAFKA_BOOTSTRAP_SERVERS"], "kafka:9092")

    def test_generated_paths_and_healthchecks_do_not_interpolate_host_variables(self):
        folder = Path(self.folder.name) / "a:b ${HOME}"
        folder.mkdir()
        self.project.path = str(folder)
        source = render_compose(self.project, "image:test", 1000, 1000)
        self.assertIn("$${HOME}", source)
        self.assertIn("$$POSTGRES_USER", source)
        self.assertNotIn("/var/run/docker.sock", source)
        self.assertNotIn("privileged:", source)

    def test_projects_do_not_share_resources_and_invalid_paths_are_rejected(self):
        first = compose_definition(self.project, "image:test", 1000, 1000)
        self.project.id = "another-project-id"
        second = compose_definition(self.project, "image:test", 1000, 1000)
        self.assertNotEqual(first["networks"], second["networks"])
        self.assertNotEqual(first["volumes"], second["volumes"])
        self.assertEqual(
            first["volumes"]["claude_config"], second["volumes"]["claude_config"]
        )
        self.assertTrue(first["volumes"]["claude_config"]["external"])
        self.assertNotEqual(
            first["volumes"]["claude_history"], second["volumes"]["claude_history"]
        )
        self.project.path = str(Path(self.folder.name) / "missing")
        with self.assertRaisesRegex(BrigError, "folder is missing"):
            compose_definition(self.project, "image:test", 1000, 1000)
        self.project.path = self.folder.name
        self.project.id = "../../escape"
        with self.assertRaisesRegex(BrigError, "invalid project ID"):
            compose_definition(self.project, "image:test", 1000, 1000)
