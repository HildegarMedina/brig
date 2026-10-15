"""Exact HTTPS destinations and model/bootstrap paths for credential injection."""

PROVIDERS = {
    "openai": ("api.openai.com", "chatgpt.com"),
    "anthropic": ("api.anthropic.com",),
    "google": ("generativelanguage.googleapis.com",),
    "openrouter": ("openrouter.ai",),
    "groq": ("api.groq.com",),
    "mistral": ("api.mistral.ai",),
    "xai": ("api.x.ai",),
    "opencode": ("opencode.ai",),
    "opencode-go": ("opencode.ai",),
}


# Credential-free health checks, forwarded without provider credentials.
PUBLIC = {
    ("api.anthropic.com", "GET", "/api/hello"),
    ("platform.claude.com", "GET", "/v1/oauth/hello"),
}


def public(host: str, method: str, path: str) -> bool:
    return (host, method, path.split("?", 1)[0]) in PUBLIC


def provider_for(host: str, path: str = "") -> str | None:
    if host == "opencode.ai":
        return (
            "opencode-go"
            if path.startswith(("/zen/go/v1/", "/inference/go/v1/"))
            else "opencode"
        )
    return next((name for name, hosts in PROVIDERS.items() if host in hosts), None)


def permitted(method: str, path: str, *, host: str | None = None) -> bool:
    path = path.split("?", 1)[0]
    # Codex account limits and the explicit action that redeems an available
    # reset credit. Keep these account operations on their exact ChatGPT origin.
    if host == "chatgpt.com" and (method, path) in (
        ("GET", "/backend-api/wham/usage"),
        ("GET", "/backend-api/wham/rate-limit-reset-credits"),
        ("POST", "/backend-api/wham/rate-limit-reset-credits/consume"),
    ):
        return True
    if host == "opencode.ai":
        # Native v1 uses /zen; current OpenCode endpoints use /inference.
        for prefix in ("/zen/v1", "/zen/go/v1", "/inference/v1", "/inference/go/v1"):
            if path.startswith(prefix + "/"):
                relative = path[len(prefix) :]
                return (method == "GET" and relative == "/models") or (
                    method == "POST"
                    and (
                        relative
                        in (
                            "/responses",
                            "/responses/compact",
                            "/chat/completions",
                            "/messages",
                            "/messages/count_tokens",
                        )
                        or (
                            relative.startswith("/models/")
                            and relative.endswith(
                                (
                                    ":generateContent",
                                    ":streamGenerateContent",
                                    ":countTokens",
                                )
                            )
                            and not any(char in relative for char in ("%", "..", "\\"))
                        )
                    )
                )
        return False
    if method == "GET":
        return path in (
            "/v1/models",
            "/backend-api/codex/models",
            "/backend-api/wham/accounts/check",
            "/backend-api/wham/config/bundle",
            "/backend-api/wham/profiles/me",
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
            "/backend-api/wham/usage/thread_usage/query",
            "/backend-api/wham/usage/thread_usage/query_v2",
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
