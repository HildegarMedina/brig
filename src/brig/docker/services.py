"""Database image conventions and initialization/connection variables."""

from dataclasses import dataclass


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
