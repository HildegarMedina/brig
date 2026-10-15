"""Injection destination guards, public login views, and streaming redaction."""

import importlib
import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mitmproxy import http
from mitmproxy.test import tflow

from brig.auth_proxy.credentials import CredentialStore
from brig.auth_proxy.injector import CredentialInjector
from brig.auth_proxy.placeholders import PLACEHOLDER, placeholder_jwt
from brig.auth_proxy.providers import permitted, provider_for
from brig.auth_proxy.redaction import Redactor
from brig.auth_proxy.run import main, prepare
from brig.auth_proxy.storage import write_json


class AuthProtocolTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.secret = "fixture-provider-key-not-for-agent"
        write_json(
            self.root / "brig-auth.json",
            {
                name: {"type": "api", "key": self.secret}
                for name in ("openai", "anthropic", "google")
            },
        )
        self.injector = CredentialInjector(CredentialStore(self.root, "opencode"))

    def flow(
        self, url="https://api.openai.com/v1/responses", method="POST", body=b"{}"
    ):
        flow = tflow.tflow()
        flow.request = http.Request.make(
            method,
            url,
            body,
            {
                "authorization": "Bearer " + PLACEHOLDER,
                "x-api-key": PLACEHOLDER,
                "cookie": "untrusted",
            },
        )
        return flow

    def test_opencode_go_and_console_use_separate_keys_for_all_inference_formats(self):
        keys = {
            "opencode": "console-provider-fixture",
            "opencode-go": "go-provider-fixture",
        }
        write_json(
            self.root / "brig-auth.json",
            {provider: {"type": "api", "key": key} for provider, key in keys.items()},
        )
        for prefix, provider in (
            ("/zen/v1", "opencode"),
            ("/zen/go/v1", "opencode-go"),
            ("/inference/v1", "opencode"),
            ("/inference/go/v1", "opencode-go"),
        ):
            for path, method, header in (
                ("/chat/completions", "POST", "authorization"),
                ("/responses", "POST", "authorization"),
                ("/responses/compact", "POST", "authorization"),
                ("/messages", "POST", "x-api-key"),
                ("/messages/count_tokens", "POST", "x-api-key"),
                ("/models", "GET", "authorization"),
                (
                    "/models/gemini-test:generateContent?key=" + PLACEHOLDER,
                    "POST",
                    "x-goog-api-key",
                ),
                ("/models/gemini-test:streamGenerateContent", "POST", "x-goog-api-key"),
                ("/models/gemini-test:countTokens", "POST", "x-goog-api-key"),
            ):
                with self.subTest(prefix=prefix, path=path):
                    flow = self.flow("https://opencode.ai" + prefix + path, method)
                    self.assertEqual(
                        provider_for(flow.request.host, flow.request.path), provider
                    )
                    self.injector.request(flow)
                    self.assertIsNone(flow.response)
                    self.assertIn(keys[provider], flow.request.headers[header])
                    self.assertNotIn("key", flow.request.query)
                    for name in ("authorization", "x-api-key", "x-goog-api-key"):
                        if name != header:
                            self.assertNotIn(name, flow.request.headers)
                    redactor = self.injector.redactors[flow.id]
                    result = redactor(keys[provider].encode()) + redactor(b"")
                    self.assertNotIn(keys[provider].encode(), result)
                    self.assertNotIn(
                        keys["opencode-go" if provider == "opencode" else "opencode"],
                        str(flow.request.headers),
                    )

    def test_opencode_credentials_are_never_added_outside_exact_model_routes(self):
        for url, method in (
            ("https://opencode.ai/v1/messages", "POST"),
            ("https://opencode.ai/zen/go/v1/files", "POST"),
            ("https://opencode.ai/inference/go/v1/billing", "GET"),
            ("https://opencode.ai/inference/go/v1/models", "DELETE"),
            (
                "https://opencode.ai/inference/go/v1/models/../bad:generateContent",
                "POST",
            ),
            (
                "https://opencode.ai/inference/go/v1/models/%2e%2e:generateContent",
                "POST",
            ),
            (
                "https://opencode.ai/inference/go/v1/models/bad\\name:generateContent",
                "POST",
            ),
            ("https://opencode.ai:444/inference/go/v1/messages", "POST"),
            ("http://opencode.ai/inference/go/v1/messages", "POST"),
        ):
            with (
                self.subTest(url=url, method=method),
                patch.object(self.injector.store, "headers") as headers,
            ):
                flow = self.flow(url, method)
                self.injector.request(flow)
                self.assertEqual(flow.response.status_code, 403)
                headers.assert_not_called()
        for host in ("opencode.ai.evil.example", "OPENCODE.AI", "opencode.ai."):
            self.assertIsNone(provider_for(host, "/inference/go/v1/messages"))
        self.assertFalse(
            permitted("POST", "/inference/go/v1/messages", host="api.openai.com")
        )

    def test_exact_origin_method_and_path_binding(self):
        self.assertEqual(provider_for("api.openai.com"), "openai")
        for host in (
            "API.OPENAI.COM",
            "api.openai.com.",
            "api.openai.com.evil.example",
            "127.0.0.1",
        ):
            self.assertIsNone(provider_for(host))
        for method, path, allowed in (
            ("POST", "/v1/responses", True),
            ("GET", "/v1/models?key=fake", True),
            ("GET", "/backend-api/wham/accounts/check", True),
            ("GET", "/backend-api/wham/config/bundle", True),
            ("POST", "/backend-api/wham/accounts/check", False),
            ("GET", "/backend-api/wham/settings/user", False),
            ("POST", "/v1beta/models/gemini:generateContent", True),
            ("POST", "/v1beta/models/../bad:generateContent", False),
            ("POST", "/v1beta/models/%2e/bad:generateContent", False),
            ("POST", "/v1beta/models/bad\\path:generateContent", False),
            ("DELETE", "/v1/models", False),
            ("GET", "/v1/responses", False),
            ("POST", "/oauth/token", False),
        ):
            self.assertEqual(permitted(method, path), allowed)
        for url, method in (
            ("http://api.openai.com/v1/responses", "POST"),
            ("https://api.openai.com:444/v1/responses", "POST"),
            ("https://api.openai.com/v1/files", "POST"),
            ("https://api.openai.com/v1/responses", "GET"),
        ):
            flow = self.flow(url, method)
            self.injector.request(flow)
            self.assertEqual(flow.response.status_code, 403)
            self.assertNotIn(self.secret, str(flow.response.content))

    def test_codex_analytics_reports_allow_only_exact_read_routes(self):
        for route in (
            "profiles/me",
            "usage/daily-token-usage-breakdown",
            "usage/credit-usage-events",
            "usage/plan_limit_history",
            "usage/daily-workspace-user-token-usage-breakdown",
            "usage/daily-workspace-user-credit-usage",
            "analytics/daily-workspace-usage-counts",
            "analytics/daily-plugin-usage-metrics",
            "analytics/daily-skill-usage-metrics",
        ):
            url = "https://chatgpt.com/backend-api/wham/" + route
            flow = self.flow(url + "?start_date=2026-10-01", "GET")
            self.injector.request(flow)
            self.assertIsNone(flow.response)
            self.assertEqual(
                flow.request.headers["authorization"], "Bearer " + self.secret
            )
            for suffix, method in (("", "POST"), ("/extra", "GET")):
                flow = self.flow(url + suffix, method)
                self.injector.request(flow)
                self.assertEqual(flow.response.status_code, 403)

    def test_codex_chat_usage_query_is_forwarded_with_credentials(self):
        for route, body in (
            ("query", b'{"thread_ids":["thread-fixture"]}'),
            (
                "query_v2",
                b'{"threads":[{"thread_id":"thread-fixture","descendant_thread_ids":[]}]}',
            ),
        ):
            url = "https://chatgpt.com/backend-api/wham/usage/thread_usage/" + route
            flow = self.flow(url, "POST", body)
            self.injector.request(flow)
            self.assertIsNone(flow.response)
            self.assertEqual(
                flow.request.headers["authorization"], "Bearer " + self.secret
            )
            self.assertEqual(flow.request.content, body)
            self.injector.response(flow)
            self.assertNotIn("authorization", flow.request.headers)
            for method, suffix in (
                ("GET", ""),
                ("DELETE", ""),
                ("POST", "/extra"),
                ("POST", "/../query"),
            ):
                flow = self.flow(url + suffix, method, body)
                self.injector.request(flow)
                self.assertEqual(flow.response.status_code, 403)

    def test_codex_can_load_usage_and_redeem_available_limit_resets(self):
        (self.root / "brig-auth.json").unlink()
        token = (
            placeholder_jwt("fixture-account").rsplit(".", 1)[0] + ".fixture-signature"
        )
        write_json(
            self.root / "auth.json",
            {"tokens": {"access_token": token, "account_id": "fixture-account"}},
        )
        injector = CredentialInjector(CredentialStore(self.root, "codex"))
        for method, path, body in (
            ("GET", "/usage", b""),
            ("GET", "/rate-limit-reset-credits", b""),
            ("GET", "/rate-limit-reset-credits?source=codex", b""),
            (
                "POST",
                "/rate-limit-reset-credits/consume",
                b'{"redeem_request_id":"fixture-request"}',
            ),
            (
                "POST",
                "/rate-limit-reset-credits/consume",
                b'{"redeem_request_id":"fixture-request","credit_id":"fixture-credit"}',
            ),
        ):
            with self.subTest(method=method, path=path, body=body):
                flow = self.flow(
                    "https://chatgpt.com/backend-api/wham" + path, method, body
                )
                flow.request.headers["chatgpt-account-id"] = "untrusted-account"
                flow.request.headers["content-type"] = "application/json"
                injector.request(flow)
                self.assertIsNone(flow.response)
                self.assertEqual(
                    flow.request.headers["authorization"], "Bearer " + token
                )
                self.assertEqual(
                    flow.request.headers["chatgpt-account-id"], "fixture-account"
                )
                self.assertNotIn("cookie", flow.request.headers)
                self.assertEqual(flow.request.content, body)
                payload = b'{"windows_reset":["primary"],"remaining":1}'
                flow.response = http.Response.make(200, payload)
                injector.responseheaders(flow)
                self.assertEqual(
                    flow.response.stream(payload) + flow.response.stream(b""), payload
                )
                injector.response(flow)
                self.assertNotIn("authorization", flow.request.headers)
                self.assertNotIn("chatgpt-account-id", flow.request.headers)

    def test_codex_limit_reset_permissions_are_bound_to_exact_chatgpt_routes(self):
        for method, path in (
            ("POST", "/usage"),
            ("POST", "/rate-limit-reset-credits"),
            ("DELETE", "/rate-limit-reset-credits"),
            ("GET", "/rate-limit-reset-credits/consume"),
            ("DELETE", "/rate-limit-reset-credits/consume"),
            ("GET", "/rate-limit-reset-credits/extra"),
            ("POST", "/rate-limit-reset-credits/consume/extra"),
            ("POST", "/rate-limit-reset-credits/../consume"),
            ("POST", "/rate-limit-reset-credits/%63onsume"),
            ("POST", "/rate-limit-reset-credits/purchase"),
            ("POST", "/accounts/send_add_credits_nudge_email"),
        ):
            with (
                self.subTest(method=method, path=path),
                patch.object(self.injector.store, "headers") as headers,
            ):
                flow = self.flow("https://chatgpt.com/backend-api/wham" + path, method)
                self.injector.request(flow)
                self.assertEqual(flow.response.status_code, 403)
                headers.assert_not_called()
        for origin in (
            "http://chatgpt.com",
            "https://chatgpt.com:444",
            "https://api.openai.com",
            "https://api.anthropic.com",
            "https://opencode.ai",
        ):
            with (
                self.subTest(origin=origin),
                patch.object(self.injector.store, "headers") as headers,
            ):
                flow = self.flow(
                    origin + "/backend-api/wham/rate-limit-reset-credits", "GET"
                )
                self.injector.request(flow)
                self.assertEqual(flow.response.status_code, 403)
                headers.assert_not_called()

    def test_websocket_handshakes_ask_clients_to_use_https(self):
        for url in (
            "https://chatgpt.com/backend-api/codex/responses",
            "https://api.openai.com/v1/responses",
        ):
            with self.subTest(url=url):
                flow = self.flow(url, "GET", b"")
                flow.request.headers["upgrade"] = "WebSocket"
                self.injector.request(flow)
                # Codex falls back to HTTPS immediately only on 426.
                self.assertEqual(flow.response.status_code, 426)
                self.assertEqual(flow.request.headers["x-api-key"], PLACEHOLDER)
                self.assertEqual(self.injector.redactors, {})
        flow = self.flow("https://example.com/socket", "GET", b"")
        flow.request.headers["upgrade"] = "websocket"
        self.injector.request(flow)
        self.assertIsNone(flow.response)

    def test_injection_replaces_untrusted_headers_and_removes_query_credentials(self):
        flow = self.flow(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent?key=untrusted"
        )
        self.injector.request(flow)
        self.assertNotIn("key", flow.request.query)
        self.assertNotIn("authorization", flow.request.headers)
        self.assertNotIn("cookie", flow.request.headers)
        self.assertEqual(flow.request.headers["x-goog-api-key"], self.secret)
        self.assertEqual(flow.request.headers["accept-encoding"], "identity")
        self.injector.response(flow)
        self.assertNotIn("x-goog-api-key", flow.request.headers)
        self.assertEqual(self.injector.redactors, {})

    def test_public_health_check_is_forwarded_without_credentials(self):
        for url in (
            "https://api.anthropic.com/api/hello",
            "https://platform.claude.com/v1/oauth/hello",
        ):
            flow = self.flow(url, "GET")
            self.injector.request(flow)
            self.assertIsNone(flow.response)
            for name in ("authorization", "x-api-key", "cookie"):
                self.assertNotIn(name, flow.request.headers)
        self.assertEqual(self.injector.redactors, {})
        for url, method in (
            ("https://api.anthropic.com/api/hello", "POST"),
            ("https://api.anthropic.com/api/oauth/profile", "GET"),
            ("https://platform.claude.com/v1/oauth/hello", "POST"),
            ("https://platform.claude.com/v1/oauth/token", "GET"),
            ("http://api.anthropic.com/api/hello", "GET"),
        ):
            flow = self.flow(url, method)
            self.injector.request(flow)
            self.assertEqual(flow.response.status_code, 403)

    def test_uncaught_adapter_failures_do_not_forward(self):
        flow = self.flow()
        with patch.object(
            self.injector.store, "headers", side_effect=RuntimeError(self.secret)
        ):
            self.injector.request(flow)
        self.assertEqual(flow.response.status_code, 401)
        self.assertNotIn(self.secret, flow.response.get_text())
        unknown = self.flow("https://example.com/path")
        self.injector.request(unknown)
        self.assertIsNone(unknown.response)

    def test_redirects_compressed_responses_and_sensitive_headers_are_blocked(self):
        for status, encoding in ((302, "identity"), (200, "gzip"), (200, "identity")):
            flow = self.flow()
            self.injector.request(flow)
            flow.response = http.Response.make(
                status,
                self.secret.encode(),
                {
                    "authorization": self.secret,
                    "set-cookie": self.secret,
                    "content-encoding": encoding,
                },
            )
            self.injector.responseheaders(flow)
            self.assertNotIn("authorization", flow.response.headers)
            self.assertNotIn("set-cookie", flow.response.headers)
            self.assertNotIn("content-length", flow.response.headers)
            if status == 302 or encoding == "gzip":
                self.assertNotEqual(flow.response.status_code, 200)
            else:
                self.assertEqual(
                    flow.response.stream(flow.response.content)
                    + flow.response.stream(b""),
                    b"[brig-redacted]",
                )
            self.injector.error(flow)
        self.injector.responseheaders(self.flow("https://example.com/path"))

    def test_streaming_filter_catches_all_chunk_boundaries_without_delaying_other_text(
        self,
    ):
        for cut in range(1, len(self.secret)):
            redactor = Redactor([self.secret, self.secret[:12], "", self.secret])
            chunks = [
                b"event: data\n",
                self.secret[:cut].encode(),
                self.secret[cut:].encode(),
                b"\ncomplete\n",
                b"",
            ]
            output = b"".join(redactor(chunk) for chunk in chunks)
            self.assertNotIn(self.secret.encode(), output)
            self.assertEqual(output, b"event: data\n[brig-redacted]\ncomplete\n")
        redactor = Redactor([])
        self.assertEqual(redactor(b"plain event"), b"plain event")

    def test_real_authentication_endpoints_never_return_real_tokens(self):
        for host, path in (
            ("auth.openai.com", "/oauth/token"),
            ("platform.claude.com", "/v1/oauth/token"),
        ):
            flow = self.flow(
                "https://" + host + path,
                body=json.dumps(
                    {"grant_type": "refresh_token", "refresh_token": PLACEHOLDER}
                ).encode(),
            )
            flow.request.headers["Content-Type"] = "application/json"
            self.injector.request(flow)
            self.assertEqual(
                json.loads(flow.response.content)["access_token"], placeholder_jwt()
            )
            flow.request.headers["Content-Type"] = "application/x-www-form-urlencoded"
            flow.request.urlencoded_form = {
                "grant_type": "refresh_token",
                "refresh_token": PLACEHOLDER,
            }
            self.injector.request(flow)
            self.assertEqual(flow.response.status_code, 200)
            flow.request.headers["Content-Type"] = "application/json"
            flow.request.content = b"{invalid"
            self.injector.request(flow)
            self.assertEqual(flow.response.status_code, 403)
            flow.request.content = b'{"grant_type":"authorization_code"}'
            self.injector.request(flow)
            self.assertEqual(flow.response.status_code, 403)
        flow = self.flow("https://claude.ai/api/account")
        self.injector.request(flow)
        self.assertEqual(flow.response.status_code, 403)

    def test_public_views_contain_no_private_ca_or_provider_token(self):
        private, public = self.root / "ca", self.root / "view"
        private.mkdir()
        public.mkdir()
        (public / "ready").write_text("stale")
        for agent in ("claude", "codex", "opencode"):
            prepare(agent, self.root, private, public)
            self.assertFalse((public / "ready").exists())
            self.assertNotIn(self.secret, (public / "auth.json").read_text())
            self.assertNotIn("PRIVATE KEY", (public / "cert.pem").read_text())
            self.assertIn("CERTIFICATE", (public / "cert.pem").read_text())
            self.assertNotIn(self.secret, (public / "environment.sh").read_text())
        self.injector.running()
        ready = public / "ready"
        CredentialInjector(self.injector.store, ready).running()
        self.assertTrue(ready.exists())
        (self.root / "brig-auth.json").unlink()
        prepare("claude", self.root, private, public)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", (public / "environment.sh").read_text())
        write_json(
            self.root / ".credentials.json",
            {"claudeAiOauth": {"accessToken": self.secret, "expiresAt": 4102444800000}},
        )
        prepare("claude", self.root, private, public)
        self.assertIn(
            "CLAUDE_CODE_OAUTH_TOKEN", (public / "environment.sh").read_text()
        )

    def test_runtime_entry_point_is_quiet_and_has_no_dump_or_insecure_flags(self):
        with (
            patch.dict(os.environ, {"BRIG_AUTH_AGENT": "codex"}),
            patch("brig.auth_proxy.run.prepare"),
            patch("brig.auth_proxy.run.mitmdump") as run,
        ):
            main()
        args = run.call_args.args[0]
        self.assertIn("-q", args)
        self.assertNotIn("ssl_insecure=true", args)
        self.assertFalse(any("dump" in arg for arg in args))
        with patch("brig.auth_proxy.run.main") as entry:
            runpy.run_module("brig.auth_proxy", run_name="__main__")
            entry.assert_called_once()
        with patch.dict(os.environ, {"BRIG_AUTH_AGENT": "codex"}):
            module = importlib.import_module("brig.auth_proxy.addon")
        self.assertEqual(module.addons[0].store.agent, "codex")
