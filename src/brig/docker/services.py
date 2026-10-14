"""Service container conventions and initialization/connection variables.

Images come from the component catalog, which verifies they are published.
"""

from dataclasses import dataclass

from brig.attachments import ATTACHMENTS_PATH, CONTEXT_PATH
from brig.docker.tools import AGENT_TOOLS


@dataclass(frozen=True)
class ServiceDefinition:
    data: str
    health: tuple[str, ...]


SERVICES = {
    "postgresql": ServiceDefinition(
        "/var/lib/postgresql/data",
        ("CMD-SHELL", 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'),
    ),
    "mysql": ServiceDefinition(
        "/var/lib/mysql",
        (
            "CMD-SHELL",
            'mysqladmin ping -h 127.0.0.1 -uroot -p"$MYSQL_ROOT_PASSWORD" --silent',
        ),
    ),
    "mariadb": ServiceDefinition(
        "/var/lib/mysql",
        ("CMD", "healthcheck.sh", "--connect", "--innodb_initialized"),
    ),
    "mongodb": ServiceDefinition(
        "/data/db",
        (
            "CMD",
            "mongosh",
            "--quiet",
            "--eval",
            "quit(db.adminCommand('ping').ok ? 0 : 1)",
        ),
    ),
    "redis": ServiceDefinition("/data", ("CMD", "redis-cli", "ping")),
    "rabbitmq": ServiceDefinition(
        "/var/lib/rabbitmq",
        ("CMD", "rabbitmq-diagnostics", "-q", "ping"),
    ),
    "kafka": ServiceDefinition(
        "/var/lib/kafka/data",
        (
            "CMD",
            "/opt/kafka/bin/kafka-broker-api-versions.sh",
            "--bootstrap-server",
            "localhost:9092",
        ),
    ),
}

# Single-node KRaft broker that clients reach by its service name.
KAFKA_ENVIRONMENT = {
    "KAFKA_NODE_ID": "1",
    "KAFKA_PROCESS_ROLES": "broker,controller",
    "KAFKA_LISTENERS": "PLAINTEXT://:9092,CONTROLLER://:9093",
    "KAFKA_ADVERTISED_LISTENERS": "PLAINTEXT://kafka:9092",
    "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
    "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
    "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
    "KAFKA_LOG_DIRS": "/var/lib/kafka/data",
    "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1",
    "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": "1",
    "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": "1",
    "KAFKA_SHARE_COORDINATOR_STATE_TOPIC_REPLICATION_FACTOR": "1",
    "KAFKA_SHARE_COORDINATOR_STATE_TOPIC_MIN_ISR": "1",
    "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS": "0",
}


def service_environment(
    name: str, password: str, root_password: str
) -> tuple[dict, dict]:
    """Return container initialization and developer connection variables."""
    if name == "postgresql":
        return (
            {
                "POSTGRES_USER": "brig",
                "POSTGRES_DB": "brig",
                "POSTGRES_PASSWORD": password,
            },
            {
                "PGHOST": name,
                "PGPORT": "5432",
                "PGUSER": "brig",
                "PGDATABASE": "brig",
                "PGPASSWORD": password,
            },
        )
    if name in ("mysql", "mariadb"):
        prefix = name.upper()
        return (
            {
                f"{prefix}_DATABASE": "brig",
                f"{prefix}_USER": "brig",
                f"{prefix}_PASSWORD": password,
                f"{prefix}_ROOT_PASSWORD": root_password,
            },
            {
                f"{prefix}_HOST": name,
                f"{prefix}_PORT": "3306",
                f"{prefix}_DATABASE": "brig",
                f"{prefix}_USER": "brig",
                f"{prefix}_PASSWORD": password,
            },
        )
    if name == "mongodb":
        return (
            {
                "MONGO_INITDB_ROOT_USERNAME": "brig",
                "MONGO_INITDB_ROOT_PASSWORD": password,
            },
            {
                "MONGODB_URI": f"mongodb://brig:{password}@mongodb:27017/brig?authSource=admin"
            },
        )
    if name == "rabbitmq":
        return (
            {"RABBITMQ_DEFAULT_USER": "brig", "RABBITMQ_DEFAULT_PASS": password},
            {
                "RABBITMQ_HOST": "rabbitmq",
                "RABBITMQ_PORT": "5672",
                "RABBITMQ_USER": "brig",
                "RABBITMQ_PASSWORD": password,
                "AMQP_URL": f"amqp://brig:{password}@rabbitmq:5672/",
                "RABBITMQ_MANAGEMENT_URL": "http://rabbitmq:15672",
            },
        )
    if name == "kafka":
        return (
            dict(KAFKA_ENVIRONMENT),
            {
                "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
                "KAFKA_HOST": "kafka",
                "KAFKA_PORT": "9092",
            },
        )
    return (
        {},
        {
            "REDIS_HOST": "redis",
            "REDIS_PORT": "6379",
            "REDIS_URL": "redis://redis:6379",
        },
    )


SERVICE_HINTS = {
    "postgresql": "PostgreSQL: host `postgresql`; use PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD",
    "mysql": "MySQL: host `mysql`; use MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD",
    "mariadb": "MariaDB: host `mariadb`; use MARIADB_HOST, MARIADB_PORT, MARIADB_DATABASE, MARIADB_USER, MARIADB_PASSWORD",
    "mongodb": "MongoDB: host `mongodb`; use MONGODB_URI",
    "redis": "Redis: host `redis`, no password; use REDIS_HOST, REDIS_PORT, REDIS_URL",
    "rabbitmq": "RabbitMQ: host `rabbitmq`, virtual host `/`; use AMQP_URL or "
    "RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASSWORD. Its HTTP "
    "management API is at RABBITMQ_MANAGEMENT_URL with the same user",
    "kafka": "Kafka: single broker at `kafka:9092`, plaintext, no authentication; "
    "use KAFKA_BOOTSTRAP_SERVERS. Topic replication factor must be 1",
}


def agent_instructions(services) -> str:
    """Tell agents they are sandboxed and which service settings are real."""
    lines = [
        "# Brig sandbox",
        "You are running inside a Brig sandbox: an isolated container with its own "
        "network. `localhost` and `127.0.0.1` refer to this container, not to the "
        "developer's machine, and you cannot reach the applications the developer "
        "runs there.",
        "Files the developer attaches with Brig are copied to "
        f"`{ATTACHMENTS_PATH}/<random>/<name>`, and reusable context lives in "
        f"`{CONTEXT_PATH}/`. These folders are hidden and git-ignored, so most "
        "search tools skip them: when the developer mentions a file you cannot "
        f"find, look there explicitly (for example `find {CONTEXT_PATH} -name "
        "'<name>'`). If several attachments share a name, ask which one to use.",
        "Besides git, curl, jq, rg and unzip, these commands are installed: "
        + ", ".join(
            f"`{command}`" for commands in AGENT_TOOLS.values() for command in commands
        )
        + ". Prefer them over ad hoc scripts, for example `ss`, `nc` and "
        "`dig` to diagnose connections. You run as an unprivileged user and "
        "cannot install system packages.",
    ]
    if not services:
        lines.append(
            "No databases, caches or message brokers are provided here. Databases, "
            "Redis, RabbitMQ, Kafka or other services mentioned in the project "
            "files are not reachable from this sandbox."
        )
        return "\n".join(lines) + "\n"
    lines += [
        "The services below are private to this sandbox. They are NOT the "
        "databases, Redis, message brokers or other services used by the application the "
        "developer runs outside Brig (locally, in staging or in production): their "
        "data differs, may be empty, and nothing you change here affects them. Do "
        "not assume data from the developer's environment exists here.",
        "Use only these connection settings, read from the environment. They take "
        "precedence over any host, port, user, password or URL mentioned in "
        "CLAUDE.md, AGENTS.md, README, .env files, docker-compose files or test "
        "configuration (for example localhost, 127.0.0.1 or postgres/postgres):",
        *(f"- {SERVICE_HINTS[name]}" for name in sorted(services)),
        "Do not start databases, caches or message brokers yourself (docker, docker compose, "
        "testcontainers or local server binaries). Never print, log or commit passwords.",
    ]
    return "\n".join(lines) + "\n"
