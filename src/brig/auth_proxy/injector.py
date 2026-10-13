"""Fail-closed credential injection at verified provider inference destinations."""

import json

from mitmproxy import http

from brig.auth_proxy.credentials import CredentialStore
from brig.auth_proxy.placeholders import PLACEHOLDER, placeholder_jwt
from brig.auth_proxy.providers import permitted, provider_for, public
from brig.auth_proxy.redaction import Redactor

SENSITIVE = (
    "authorization",
    "x-api-key",
    "x-goog-api-key",
    "cookie",
    "chatgpt-account-id",
)


class CredentialInjector:
    def __init__(self, store: CredentialStore, ready=None):
        self.store = store
        self.ready = ready
        self.redactors = {}

    def running(self):
        if self.ready is not None:
            self.ready.write_text("ready")

    @staticmethod
    def deny(flow, status=403):
        flow.response = http.Response.make(
            status,
            b"Brig credential proxy rejected this request. Sign in with brig auth from the host.",
            {"Content-Type": "text/plain"},
        )

    def request(self, flow: http.HTTPFlow):
        if flow.request.scheme == "https" and public(
            flow.request.host, flow.request.method, flow.request.path
        ):
            for name in SENSITIVE:
                flow.request.headers.pop(name, None)
            return
        if flow.request.host in (
            "auth.openai.com",
            "platform.claude.com",
            "console.anthropic.com",
            "claude.ai",
        ):
            self.deny(flow)
            if flow.request.method == "POST" and flow.request.path in (
                "/oauth/token",
                "/v1/oauth/token",
            ):
                try:
                    body = (
                        json.loads(flow.request.get_text())
                        if "json" in flow.request.headers.get("content-type", "")
                        else dict(flow.request.urlencoded_form)
                    )
                    if (
                        body.get("grant_type") == "refresh_token"
                        and body.get("refresh_token") == PLACEHOLDER
                    ):
                        flow.response = http.Response.make(
                            200,
                            json.dumps(
                                {
                                    "access_token": placeholder_jwt(),
                                    "id_token": placeholder_jwt(),
                                    "refresh_token": PLACEHOLDER,
                                    "token_type": "Bearer",
                                    "expires_in": 3600,
                                }
                            ),
                            {"Content-Type": "application/json"},
                        )
                except ValueError:
                    pass
            return
        provider = provider_for(flow.request.host)
        if provider is None:
            return
        try:
            if (
                flow.request.scheme != "https"
                or flow.request.port != 443
                or not permitted(flow.request.method, flow.request.path)
            ):
                self.deny(flow)
                return
            for name in SENSITIVE:
                flow.request.headers.pop(name, None)
            flow.request.query.pop("key", None)
            flow.request.headers["accept-encoding"] = "identity"
            headers, secrets = self.store.headers(provider)
            flow.request.headers.update(headers)
            self.redactors[flow.id] = Redactor(secrets)
        except Exception:
            # Addon exceptions must never silently forward an unguarded request.
            self.deny(flow, 401)

    def responseheaders(self, flow: http.HTTPFlow):
        redactor = self.redactors.get(flow.id)
        if redactor is None:
            return
        if 300 <= flow.response.status_code < 400:
            self.deny(flow)
        if (
            flow.response.headers.get("content-encoding", "identity").lower()
            != "identity"
        ):
            self.deny(flow, 502)
        flow.response.headers.pop("content-length", None)
        for name in (*SENSITIVE, "set-cookie"):
            flow.response.headers.pop(name, None)
        flow.response.stream = redactor

    def response(self, flow: http.HTTPFlow):
        self.redactors.pop(flow.id, None)
        for name in SENSITIVE:
            flow.request.headers.pop(name, None)

    def error(self, flow: http.HTTPFlow):
        self.response(flow)
