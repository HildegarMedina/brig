"""Public inert login documents and CA export; never copy a native secret file."""

import base64
import json
from datetime import UTC, datetime

from brig.auth_proxy.credentials import CredentialStore, claims
from brig.auth_proxy.providers import PROVIDERS
from brig.auth_proxy.storage import CredentialError

PLACEHOLDER = "sk-brig-proxy-managed-not-a-real-credential"
EXPIRES = 4102444800000


def placeholder_jwt(account_id: str = "brig-proxy", user_id: str | None = None) -> str:
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return (
        encode({"alg": "none"})
        + "."
        + encode(
            {
                "exp": EXPIRES // 1000,
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": account_id,
                    "chatgpt_user_id": user_id,
                    "chatgpt_plan_type": "plus",
                },
            }
        )
        + ".brig-placeholder"
    )


def login_view(store: CredentialStore) -> dict:
    if store.agent == "codex":
        try:
            _, raw, record, _ = store.record("openai")
        except CredentialError:
            record = {"type": "api"}
        if record.get("type") == "oauth":
            # Routing discovery matches this non-secret ID against the account
            # list. Tokens and JWT signatures remain inert placeholders.
            account_id = record.get("accountId") or claims(
                record.get("access") or ""
            ).get("https://api.openai.com/auth", {}).get(
                "chatgpt_account_id", "brig-proxy"
            )
            if not isinstance(account_id, str) or any(
                ord(char) < 33 or ord(char) > 126 for char in account_id
            ):
                raise CredentialError("Invalid account identifier")
            user_claims = claims(
                raw.get("tokens", {}).get("id_token") or record.get("access") or ""
            ).get("https://api.openai.com/auth", {})
            user_id = user_claims.get("chatgpt_user_id") or user_claims.get("user_id")
            if user_id is not None and (
                not isinstance(user_id, str)
                or not user_id
                or any(ord(char) < 33 or ord(char) > 126 for char in user_id)
            ):
                raise CredentialError("Invalid user identifier")
            return {
                "auth_mode": "chatgpt",
                "tokens": {
                    "id_token": placeholder_jwt(account_id, user_id),
                    "access_token": placeholder_jwt(account_id, user_id),
                    "refresh_token": PLACEHOLDER,
                    "account_id": account_id,
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
