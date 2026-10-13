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
