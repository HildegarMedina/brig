"""Exact HTTPS destinations and model/bootstrap paths for credential injection."""

PROVIDERS = {
    "openai": ("api.openai.com", "chatgpt.com"),
    "anthropic": ("api.anthropic.com",),
    "google": ("generativelanguage.googleapis.com",),
    "openrouter": ("openrouter.ai",),
    "groq": ("api.groq.com",),
    "mistral": ("api.mistral.ai",),
    "xai": ("api.x.ai",),
}


# Credential-free health checks, forwarded without provider credentials.
PUBLIC = {
    ("api.anthropic.com", "GET", "/api/hello"),
    ("platform.claude.com", "GET", "/v1/oauth/hello"),
}


def public(host: str, method: str, path: str) -> bool:
    return (host, method, path.split("?", 1)[0]) in PUBLIC


def provider_for(host: str) -> str | None:
    return next((name for name, hosts in PROVIDERS.items() if host in hosts), None)


def permitted(method: str, path: str) -> bool:
    path = path.split("?", 1)[0]
    if method == "GET":
        return path in (
            "/v1/models",
            "/backend-api/codex/models",
            "/backend-api/wham/accounts/check",
            "/backend-api/wham/config/bundle",
            "/backend-api/wham/usage/daily-token-usage-breakdown",
            "/backend-api/wham/usage/credit-usage-events",
            "/backend-api/wham/usage/plan_limit_history",
            "/backend-api/wham/usage/daily-workspace-user-token-usage-breakdown",
            "/backend-api/wham/usage/daily-workspace-user-credit-usage",
            "/backend-api/wham/analytics/daily-workspace-usage-counts",
            "/backend-api/wham/analytics/daily-plugin-usage-metrics",
            "/backend-api/wham/analytics/daily-skill-usage-metrics",
            "/api/v1/models",
            "/openai/v1/models",
            "/v1beta/models",
        )
    return method == "POST" and (
        path
        in (
            "/v1/responses",
            "/v1/responses/compact",
            "/backend-api/codex/responses",
            "/backend-api/codex/responses/compact",
            "/v1/chat/completions",
            "/api/v1/chat/completions",
            "/openai/v1/chat/completions",
            "/v1/messages",
            "/v1/messages/count_tokens",
            "/v1/complete",
        )
        or (
            path.startswith("/v1beta/models/")
            and path.endswith(
                (":generateContent", ":streamGenerateContent", ":countTokens")
            )
            and all(char not in path for char in ("%", "..", "\\"))
        )
    )
