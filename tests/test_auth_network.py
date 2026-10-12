"""Real TLS proxy traffic with a local provider fixture; no live credentials/API."""

import asyncio
import json
import ssl
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mitmproxy import http, options
from mitmproxy.certs import CertStore
from mitmproxy.tools.dump import DumpMaster

from brig.auth_proxy.credentials import CredentialStore
from brig.auth_proxy.injector import CredentialInjector
from brig.auth_proxy.storage import write_json


class AuthNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_tls_client_uses_proxy_without_receiving_upstream_credential(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            token = "fixture-private-key-only-upstream-sees"
            write_json(
                root / "brig-auth.json", {"openai": {"type": "api", "key": token}}
            )
            observed = []

            class Provider(BaseHTTPRequestHandler):
                def do_POST(self):
                    observed.append(self.headers.get("Authorization"))
                    self.rfile.read(int(self.headers["Content-Length"]))
                    body = (
                        "data: " + json.dumps({"echo": observed[-1]}) + "\n\n"
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            certificate = root / "ca"
            certificate.mkdir()
            CertStore.from_store(certificate, "mitmproxy", 2048)
            settings = options.Options(
                listen_host="127.0.0.1",
                listen_port=0,
                confdir=str(certificate),
                upstream_cert=False,
            )
            master = DumpMaster(settings, with_termlog=False, with_dumper=False)
            master.addons.add(CredentialInjector(CredentialStore(root, "codex")))
            port = server.server_port

            class LocalFixtureRouting:
                def request(self, flow):
                    if flow.response is not None:
                        return
                    # Test-only routing; every upstream remains on localhost.
                    if flow.request.host != "api.openai.com":
                        flow.response = http.Response.make(403, b"fixture denied")
                        return
                    flow.request.host = "127.0.0.1"
                    flow.request.port = port
                    flow.request.scheme = "http"

            master.addons.add(LocalFixtureRouting())
            running = asyncio.create_task(master.run())
            try:
                for _ in range(100):
                    addresses = master.addons.get("proxyserver").listen_addrs()
                    if addresses:
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(addresses)
                proxy = f"http://127.0.0.1:{addresses[0][1]}"
                context = ssl.create_default_context(
                    cafile=str(certificate / "mitmproxy-ca-cert.pem")
                )
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"https": proxy}),
                    urllib.request.HTTPSHandler(context=context),
                )
                request = urllib.request.Request(
                    "https://api.openai.com/v1/responses",
                    b"{}",
                    {
                        "Authorization": "Bearer placeholder",
                        "Content-Type": "application/json",
                    },
                )

                def call():
                    with opener.open(request, timeout=10) as response:
                        return response.read()

                result = await asyncio.to_thread(call)
                self.assertEqual(observed, ["Bearer " + token])
                self.assertNotIn(token.encode(), result)
                self.assertIn(b"[brig-redacted]", result)
            finally:
                master.shutdown()
                await running
