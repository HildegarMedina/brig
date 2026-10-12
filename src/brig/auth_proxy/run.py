"""Trusted proxy bootstrap; private CA keys and provider logins stay here."""

import os
from pathlib import Path

import certifi
from mitmproxy.certs import CertStore
from mitmproxy.tools.main import mitmdump

from brig.auth_proxy.credentials import CredentialStore
from brig.auth_proxy.placeholders import login_view
from brig.auth_proxy.storage import write_json


def prepare(agent: str, secrets: Path, private: Path, public: Path):
    private.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    CertStore.from_store(private, "mitmproxy", 2048)
    certificate = (private / "mitmproxy-ca-cert.pem").read_bytes()
    (public / "cert.pem").write_bytes(Path(certifi.where()).read_bytes() + certificate)
    (public / "ready").unlink(missing_ok=True)
    store = CredentialStore(secrets, agent)
    write_json(public / "auth.json", login_view(store))
    variable = ""
    if agent == "claude":
        try:
            _, _, record, _ = store.record("anthropic")
            variable = (
                "ANTHROPIC_AUTH_TOKEN"
                if record.get("type") == "api"
                else "CLAUDE_CODE_OAUTH_TOKEN"
            )
        except Exception:
            variable = "ANTHROPIC_AUTH_TOKEN"
    (public / "environment.sh").write_text(
        f"export {variable}=sk-brig-proxy-managed-not-a-real-credential\n"
        if variable
        else "# Brig-managed authentication\n"
    )


def main():
    prepare(
        os.environ["BRIG_AUTH_AGENT"],
        Path("/secrets"),
        Path("/certificates"),
        Path("/public"),
    )
    mitmdump(
        [
            "-q",
            "--listen-host",
            "0.0.0.0",
            "--listen-port",
            "8080",
            "--set",
            "confdir=/certificates",
            "--set",
            "connection_strategy=lazy",
            "--set",
            "block_global=false",
            "--set",
            "termlog_verbosity=error",
            "-s",
            str(Path(__file__).with_name("addon.py")),
        ]
    )
