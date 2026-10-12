"""Public inert login documents and CA export; never copy a native secret file."""

import base64
import json
from datetime import UTC, datetime

from brig.auth_proxy.credentials import CredentialStore
from brig.auth_proxy.providers import PROVIDERS
from brig.auth_proxy.storage import CredentialError

PLACEHOLDER = "sk-brig-proxy-managed-not-a-real-credential"
EXPIRES = 4102444800000


def placeholder_jwt() -> str:
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return (
        encode({"alg": "none"})
        + "."
        + encode(
            {
                "exp": EXPIRES // 1000,
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "brig-proxy",
                    "chatgpt_plan_type": "plus",
                },
            }
        )
        + ".brig-placeholder"
    )


def login_view(store: CredentialStore) -> dict:
    if store.agent == "codex":
        try:
            _, _, record, _ = store.record("openai")
        except CredentialError:
            record = {"type": "api"}
        if record.get("type") == "oauth":
            return {
                "auth_mode": "chatgpt",
                "tokens": {
                    "id_token": placeholder_jwt(),
                    "access_token": placeholder_jwt(),
                    "refresh_token": PLACEHOLDER,
                    "account_id": "brig-proxy",
                },
                "last_refresh": datetime.now(UTC).isoformat(),
            }
        return {"OPENAI_API_KEY": PLACEHOLDER}
    if store.agent == "claude":
        return {
            "claudeAiOauth": {
                "accessToken": PLACEHOLDER,
                "refreshToken": PLACEHOLDER,
                "expiresAt": EXPIRES,
                "scopes": ["user:inference", "user:profile"],
                "subscriptionType": "max",
            }
        }
    records = {}
    for provider in PROVIDERS:
        try:
            _, _, record, _ = store.record(provider)
        except CredentialError:
            continue
        records[provider] = (
            {
                "type": "oauth",
                "access": placeholder_jwt(),
                "refresh": PLACEHOLDER,
                "expires": EXPIRES,
                "accountId": "brig-proxy",
            }
            if record.get("type") == "oauth"
            else {"type": "api", "key": PLACEHOLDER}
        )
    return records
