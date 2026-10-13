"""Database image conventions and initialization/connection variables."""

from dataclasses import dataclass

from brig.attachments import ATTACHMENTS_PATH, CONTEXT_PATH
from brig.docker.tools import AGENT_TOOLS


@dataclass(frozen=True)
class ServiceDefinition:
    image: str
    data: str
    health: tuple[str, ...]


SERVICES = {
    "postgresql": ServiceDefinition(
        "postgres",
        "/var/lib/postgresql/data",
        ("CMD-SHELL", 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'),
    ),
    "mysql": ServiceDefinition(
        "mysql",
        "/var/lib/mysql",
        (
            "CMD-SHELL",
            'mysqladmin ping -h 127.0.0.1 -uroot -p"$MYSQL_ROOT_PASSWORD" --silent',
        ),
    ),
    "mariadb": ServiceDefinition(
        "mariadb",
        "/var/lib/mysql",
        ("CMD", "healthcheck.sh", "--connect", "--innodb_initialized"),
    ),
    "mongodb": ServiceDefinition(
        "mongo",
        "/data/db",
        (
            "CMD",
            "mongosh",
            "--quiet",
            "--eval",
            "quit(db.adminCommand('ping').ok ? 0 : 1)",
        ),
    ),
    "redis": ServiceDefinition("redis", "/data", ("CMD", "redis-cli", "ping")),
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
            "No databases or caches are provided here. Databases, Redis or other "
            "services mentioned in the project files are not reachable from this sandbox."
        )
        return "\n".join(lines) + "\n"
    lines += [
        "The databases and caches below are private to this sandbox. They are NOT "
        "the databases, Redis or other services used by the application the "
        "developer runs outside Brig (locally, in staging or in production): their "
        "data differs, may be empty, and nothing you change here affects them. Do "
        "not assume data from the developer's environment exists here.",
        "Use only these connection settings, read from the environment. They take "
        "precedence over any host, port, user, password or URL mentioned in "
        "CLAUDE.md, AGENTS.md, README, .env files, docker-compose files or test "
        "configuration (for example localhost, 127.0.0.1 or postgres/postgres):",
        *(f"- {SERVICE_HINTS[name]}" for name in sorted(services)),
        "Do not start databases or caches yourself (docker, docker compose, "
        "testcontainers or local server binaries). Never print, log or commit passwords.",
    ]
    return "\n".join(lines) + "\n"
