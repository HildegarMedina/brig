"""A successful host login switches away from an explicitly stored API key."""

import hashlib
import json
from pathlib import Path

from brig.auth_proxy.credentials import CredentialStore, secret
from brig.auth_proxy.providers import PROVIDERS
from brig.auth_proxy.storage import (
    CredentialError,
    credential_lock,
    read_json,
    write_json,
)


def native_login_digests(directory: Path, agent: str):
    records = {}
    store = CredentialStore(directory, agent)
    for provider in PROVIDERS:
        try:
            _, _, record, _ = store.record(provider, include_managed=False)
            secret(
                record.get("access")
                if record.get("type") == "oauth"
                else record.get("key")
            )
            records[provider] = hashlib.sha256(
                json.dumps(record, sort_keys=True).encode()
            ).hexdigest()
        except (CredentialError, AttributeError):
            continue
    return records


def snapshot_login(directory: Path, agent: str):
    with credential_lock(directory):
        # Persist digests, never additional plaintext copies of native secrets.
        write_json(
            directory / ".brig-login-before.json",
            native_login_digests(directory, agent),
        )


def clear_override(directory: Path, agent: str):
    with credential_lock(directory):
        if agent == "opencode":
            before = read_json(directory / ".brig-login-before.json")
            after = native_login_digests(directory, agent)
            if not isinstance(before, dict) or not after:
                raise CredentialError(
                    "Native login did not save supported provider credentials"
                )
            providers = [
                provider
                for provider, digest in after.items()
                if before.get(provider) != digest
            ]
        else:
            provider = "anthropic" if agent == "claude" else "openai"
            _, _, record, _ = CredentialStore(directory, agent).record(
                provider, include_managed=False
            )
            secret(
                record.get("access")
                if record.get("type") == "oauth"
                else record.get("key")
            )
            providers = [provider]
        path = directory / "brig-auth.json"
        managed = read_json(path)
        if isinstance(managed, dict) and any(
            provider in managed for provider in providers
        ):
            for provider in providers:
                managed.pop(provider, None)
            write_json(path, managed)
        if agent == "opencode":
            (directory / ".brig-login-before.json").unlink(missing_ok=True)


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


def configured(directory: Path, agent: str) -> bool:
    """Inspect presence without printing, refreshing, or exporting credentials."""
    providers = (
        PROVIDERS
        if agent == "opencode"
        else ("anthropic" if agent == "claude" else "openai",)
    )
    for provider in providers:
        try:
            _, _, record, _ = CredentialStore(directory, agent).record(provider)
            secret(
                record.get("access")
                if record.get("type") == "oauth"
                else record.get("key")
            )
            return True
        except (CredentialError, AttributeError):
            continue
    return False
