"""Native login adapters; refresh and secrets never leave this trusted process."""

import base64
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from brig.auth_proxy.storage import (
    CredentialError,
    credential_lock,
    read_json,
    write_json,
)

OPENAI_CLIENT = "app_EMoamEEZ73f0CkXaXp7hrann"
CLAUDE_CLIENT = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CredentialError("Credential refresh redirected unexpectedly")


def claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        value = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError):
        return {}


def secret(value) -> str:
    if (
        not isinstance(value, str)
        or not 8 <= len(value) <= 16384
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
    ):
        raise CredentialError("Invalid credential value")
    return value


def refresh(provider: str, token: str) -> dict:
    endpoint, client = (
        ("https://auth.openai.com/oauth/token", OPENAI_CLIENT)
        if provider == "openai"
        else ("https://platform.claude.com/v1/oauth/token", CLAUDE_CLIENT)
    )
    payload = json.dumps(
        {"grant_type": "refresh_token", "client_id": client, "refresh_token": token}
    ).encode()
    request = urllib.request.Request(
        endpoint, payload, {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=30
        ) as response:
            content = response.read(1024 * 1024 + 1)
        value = json.loads(content)
        if not isinstance(value, dict) or len(content) > 1024 * 1024:
            raise CredentialError("Invalid refresh response")
        secret(value.get("access_token"))
        return value
    except (OSError, ValueError) as error:
        raise CredentialError(
            "Credential refresh failed; sign in from the host"
        ) from error


class CredentialStore:
    def __init__(self, directory: Path, agent: str):
        self.directory, self.agent = directory, agent

    def record(self, provider: str, *, include_managed=True):
        managed = self.directory / "brig-auth.json"
        raw = read_json(managed)
        if include_managed and isinstance(raw, dict) and provider in raw:
            return managed, raw, raw[provider], "managed"
        if self.agent == "codex" and provider == "openai":
            path = self.directory / "auth.json"
            raw = read_json(path)
            if isinstance(raw, dict):
                if raw.get("OPENAI_API_KEY"):
                    return (
                        path,
                        raw,
                        {"type": "api", "key": raw["OPENAI_API_KEY"]},
                        "codex-api",
                    )
                tokens = raw.get("tokens")
                if isinstance(tokens, dict):
                    return (
                        path,
                        raw,
                        {
                            "type": "oauth",
                            "access": tokens.get("access_token"),
                            "refresh": tokens.get("refresh_token"),
                            "accountId": tokens.get("account_id"),
                        },
                        "codex-oauth",
                    )
        if self.agent == "claude" and provider == "anthropic":
            path = self.directory / ".credentials.json"
            raw = read_json(path)
            if isinstance(raw, dict) and isinstance(raw.get("claudeAiOauth"), dict):
                token = raw["claudeAiOauth"]
                return (
                    path,
                    raw,
                    {
                        "type": "oauth",
                        "access": token.get("accessToken"),
                        "refresh": token.get("refreshToken"),
                        "expires": token.get("expiresAt"),
                    },
                    "claude-oauth",
                )
        if self.agent == "opencode":
            path = self.directory / "auth.json"
            raw = read_json(path)
            if isinstance(raw, dict) and provider in raw:
                return path, raw, raw[provider], "opencode"
            path = self.directory / "brig-export.json"
            raw = read_json(path)
            if isinstance(raw, list):
                for entry in raw:
                    if (
                        isinstance(entry, dict)
                        and entry.get("integrationID") == provider
                        and entry.get("active")
                    ):
                        return path, raw, entry["value"], entry
        raise CredentialError("No supported credential; run brig auth from the host")

    def headers(self, provider: str) -> tuple[dict[str, str], list[str]]:
        with credential_lock(self.directory):
            path, raw, record, kind = self.record(provider)
            if not isinstance(record, dict):
                raise CredentialError("Unsupported credential record")
            if record.get("type") == "api":
                token = secret(record.get("key"))
                return (
                    {"x-api-key": token}
                    if provider == "anthropic"
                    else {"x-goog-api-key": token}
                    if provider == "google"
                    else {"Authorization": f"Bearer {token}"}
                ), [token]
            if record.get("type") != "oauth" or provider not in ("openai", "anthropic"):
                raise CredentialError("Unsupported authentication method")
            token = secret(record.get("access"))
            expires = record.get("expires", claims(token).get("exp", 0) * 1000)
            if not isinstance(expires, (int, float)):
                raise CredentialError("Invalid credential expiry")
            secrets = [token]
            if record.get("refresh"):
                secrets.append(secret(record["refresh"]))
            if expires < (time.time() + 60) * 1000:
                updated = refresh(provider, secret(record.get("refresh")))
                token = secret(updated["access_token"])
                lifetime = updated.get("expires_in", 3600)
                if type(lifetime) not in (int, float) or not 1 <= lifetime <= 31536000:
                    raise CredentialError("Invalid refreshed credential lifetime")
                secret(updated.get("refresh_token", record["refresh"]))
                record.update(
                    access=token,
                    refresh=updated.get("refresh_token", record["refresh"]),
                    expires=(time.time() + lifetime) * 1000,
                )
                if kind == "codex-oauth":
                    raw["tokens"].update(
                        access_token=token, refresh_token=record["refresh"]
                    )
                    raw["last_refresh"] = datetime.now(UTC).isoformat()
                    if "id_token" in updated:
                        raw["tokens"]["id_token"] = updated["id_token"]
                elif kind == "claude-oauth":
                    raw["claudeAiOauth"].update(
                        accessToken=token,
                        refreshToken=record["refresh"],
                        expiresAt=record["expires"],
                    )
                write_json(path, raw)
                secrets.extend([token, secret(record["refresh"])])
            headers = {"Authorization": f"Bearer {token}"}
            account = (
                record.get("accountId")
                or record.get("metadata", {}).get("accountID")
                or claims(token)
                .get("https://api.openai.com/auth", {})
                .get("chatgpt_account_id")
            )
            if provider == "openai" and account:
                if not isinstance(account, str) or any(
                    ord(char) < 33 or ord(char) > 126 for char in account
                ):
                    raise CredentialError("Invalid account identifier")
                headers["ChatGPT-Account-Id"] = account
            return headers, secrets
