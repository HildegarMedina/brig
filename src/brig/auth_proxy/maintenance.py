"""A successful host login switches away from an explicitly stored API key."""

from pathlib import Path

from brig.auth_proxy.credentials import CredentialStore, secret
from brig.auth_proxy.storage import credential_lock, read_json, write_json


def clear_override(directory: Path, agent: str):
    provider = "anthropic" if agent == "claude" else "openai"
    with credential_lock(directory):
        _, _, record, _ = CredentialStore(directory, agent).record(
            provider, include_managed=False
        )
        secret(
            record.get("access") if record.get("type") == "oauth" else record.get("key")
        )
        path = directory / "brig-auth.json"
        managed = read_json(path)
        if isinstance(managed, dict) and provider in managed:
            managed.pop(provider)
            write_json(path, managed)


def set_api_key(directory: Path, provider: str, key: str):
    secret(key)
    with credential_lock(directory):
        path = directory / "brig-auth.json"
        records = read_json(path) or {}
        if not isinstance(records, dict):
            from brig.auth_proxy.storage import CredentialError

            raise CredentialError("Invalid managed credential store")
        records[provider] = {"type": "api", "key": key}
        write_json(path, records)
