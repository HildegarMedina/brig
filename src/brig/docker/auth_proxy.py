"""Trusted credential services, private networks, and public-only agent views."""

from importlib.resources import files


def proxy_sources() -> dict[str, str]:
    package = files("brig.auth_proxy")
    return {"proxy/brig/__init__.py": ""} | {
        f"proxy/brig/auth_proxy/{path.name}": path.read_text(encoding="utf-8")
        for path in package.iterdir()
        if path.name.endswith(".py")
    }


def proxy_image_lines() -> list[str]:
    return [
        "FROM python:3.12-slim-bookworm AS credential_proxy",
        "ARG BRIG_UID=1000",
        "ARG BRIG_GID=1000",
        "RUN pip install --no-cache-dir mitmproxy==12.2.3 && \\",
        '    groupadd --gid "$BRIG_GID" brig && useradd --uid "$BRIG_UID" --gid brig --create-home brig && \\',
        "    mkdir -p /secrets /certificates /public && chown brig:brig /secrets /certificates /public && chmod 700 /secrets /certificates /public",
        "COPY --chown=brig:brig proxy/ /opt/brig-proxy/",
        "ENV PYTHONPATH=/opt/brig-proxy",
        "USER brig",
        'CMD ["python", "-m", "brig.auth_proxy"]',
        "",
    ]


def add_credential_proxy(
    agent, service, services, volumes, networks, prefix, image, uid, gid, shared
):
    name = f"credential_{agent}"
    private = f"credential_{agent}_ca"
    public = f"credential_{agent}_view"
    network = f"credential_{agent}"
    labels = {
        "org.brig.project-id": service["labels"]["org.brig.project-id"],
        "org.brig.auth-proxy": agent,
    }
    for key in (private, public):
        volumes[key] = {"name": f"{prefix}-{key.replace('_', '-')}", "labels": labels}
    networks[network] = {
        "name": f"{prefix}-credential-{agent}",
        "internal": True,
        "labels": labels,
    }
    services[name] = {
        "image": f"{image}-credential-proxy",
        "build": {
            "context": ".",
            "dockerfile": "Dockerfile",
            "target": "credential_proxy",
            "args": {"BRIG_UID": str(uid), "BRIG_GID": str(gid)},
        },
        "container_name": f"{prefix}-credential-{agent}",
        "labels": labels,
        "init": True,
        "environment": {"BRIG_AUTH_AGENT": agent},
        "volumes": [
            {"type": "volume", "source": shared, "target": "/secrets"},
            {"type": "volume", "source": private, "target": "/certificates"},
            {"type": "volume", "source": public, "target": "/public"},
        ],
        "networks": [network, "credential_egress"],
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "healthcheck": {
            "test": [
                "CMD",
                "python",
                "-c",
                "import pathlib,socket; assert pathlib.Path('/public/ready').exists(); socket.create_connection(('127.0.0.1',8080),2).close()",
            ],
            "interval": "2s",
            "timeout": "3s",
            "retries": 60,
        },
    }
    service["networks"] = ["default", network]
    service.setdefault("depends_on", {})[name] = {"condition": "service_healthy"}
    service["volumes"].append(
        {
            "type": "volume",
            "source": public,
            "target": "/opt/brig-auth",
            "read_only": True,
        }
    )
    cert = "/opt/brig-auth/cert.pem"
    service["environment"] = {
        **{
            key: f"http://{name}:8080"
            for key in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            )
        },
        **{
            key: cert
            for key in (
                "SSL_CERT_FILE",
                "CODEX_CA_CERTIFICATE",
                "NODE_EXTRA_CA_CERTS",
                "REQUESTS_CA_BUNDLE",
                "CURL_CA_BUNDLE",
            )
        },
        "NO_PROXY": "localhost,127.0.0.1,postgresql,mysql,mariadb,mongodb,redis",
    }
    service["command"] = [
        "/bin/sh",
        "-ec",
        'mkdir -p "$BRIG_AUTH_CONFIG"; cp /opt/brig-auth/auth.json "$BRIG_AUTH_CONFIG/$BRIG_AUTH_FILE"; exec sleep infinity',
    ]
    service["environment"].update(
        BRIG_AUTH_CONFIG=service.pop("brig_auth_config"),
        BRIG_AUTH_FILE=".credentials.json" if agent == "claude" else "auth.json",
    )
