"""Native credential adapters and renewal never return secrets in login views."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from brig.auth_proxy.credentials import (
    CredentialStore,
    NoRedirect,
    claims,
    refresh,
    secret,
)
from brig.auth_proxy.placeholders import (
    EXPIRES,
    PLACEHOLDER,
    login_view,
    placeholder_jwt,
)
from brig.auth_proxy.storage import (
    CredentialError,
    credential_lock,
    read_json,
    write_json,
)


class AuthCredentialTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.token = "real-fixture-secret-never-displayed"
        self.future = EXPIRES

    def write(self, name, raw):
        path = self.root / name
        write_json(path, raw)
        return path

    def test_json_storage_bounds_errors_and_atomic_rollback(self):
        path = self.root / "file"
        self.assertIsNone(read_json(path))
        for value in (b"{", b"\xff", b"x" * (1024 * 1024 + 1)):
            path.write_bytes(value)
            with self.assertRaises(CredentialError):
                read_json(path)
        with (
            patch.object(Path, "open", side_effect=PermissionError),
            self.assertRaises(CredentialError),
        ):
            read_json(path)
        write_json(path, {"key": self.token})
        before = path.read_bytes()
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with (
            patch("brig.auth_proxy.storage.os.replace", side_effect=OSError),
            self.assertRaises(CredentialError),
        ):
            write_json(path, {})
        self.assertEqual(path.read_bytes(), before)
        with (
            patch.object(Path, "mkdir", side_effect=OSError),
            self.assertRaises(CredentialError),
        ):
            write_json(path, {})
        with credential_lock(self.root):
            self.assertTrue((self.root / ".brig-auth.lock").exists())
        with (
            patch.object(Path, "open", side_effect=OSError),
            self.assertRaises(CredentialError),
            credential_lock(self.root),
        ):
            pass

    def test_jwt_and_secret_validation(self):
        self.assertGreater(claims(placeholder_jwt())["exp"], 2000000000)
        for token in ("invalid", "x.!!.z", "x.bnVsbA.z", "x.W10.z"):
            self.assertEqual(claims(token), {})
        for value in (
            None,
            "",
            "short",
            "a" * 16385,
            "fixture\nsecret",
            "fixture sécret",
        ):
            with self.assertRaises(CredentialError):
                secret(value)
        self.assertEqual(secret(self.token), self.token)

    def test_managed_api_credentials_have_provider_specific_headers(self):
        self.write(
            "brig-auth.json",
            {
                name: {"type": "api", "key": self.token}
                for name in ("openai", "anthropic", "google")
            },
        )
        store = CredentialStore(self.root, "opencode")
        for provider, name in (
            ("openai", "Authorization"),
            ("anthropic", "x-api-key"),
            ("google", "x-goog-api-key"),
        ):
            headers, secrets = store.headers(provider)
            self.assertIn(self.token, headers[name])
            self.assertEqual(secrets, [self.token])
        for record in (
            [],
            {"type": "unsupported"},
            {"type": "oauth", "access": self.token},
        ):
            self.write("brig-auth.json", {"google": record})
            with self.assertRaises(CredentialError):
                store.headers("google")

    def test_codex_api_and_chatgpt_login_are_reused(self):
        self.write("auth.json", {"OPENAI_API_KEY": self.token})
        store = CredentialStore(self.root, "codex")
        self.assertIn(self.token, store.headers("openai")[0]["Authorization"])
        self.assertEqual(login_view(store), {"OPENAI_API_KEY": PLACEHOLDER})
        self.write(
            "auth.json",
            {
                "tokens": {
                    "access_token": placeholder_jwt(),
                    "refresh_token": self.token,
                    "account_id": "account-fixture",
                }
            },
        )
        headers, _ = store.headers("openai")
        self.assertEqual(headers["ChatGPT-Account-Id"], "account-fixture")
        self.assertNotIn(self.token, json.dumps(login_view(store)))
        self.assertEqual(login_view(store)["auth_mode"], "chatgpt")
        view = login_view(store)
        self.assertEqual(view["tokens"]["account_id"], "account-fixture")
        self.assertEqual(
            claims(view["tokens"]["access_token"])["https://api.openai.com/auth"][
                "chatgpt_account_id"
            ],
            "account-fixture",
        )
        self.write("auth.json", [])
        with self.assertRaises(CredentialError):
            store.headers("openai")
        self.assertIn("OPENAI_API_KEY", login_view(store))

    def test_codex_public_account_id_keeps_tokens_inert_and_rejects_invalid_ids(self):
        for account in (None, "bad\naccount", 7):
            self.write(
                "brig-auth.json",
                {
                    "openai": {
                        "type": "oauth",
                        "access": self.token,
                        "accountId": account,
                    }
                },
            )
            store = CredentialStore(self.root, "codex")
            if account is None:
                view = login_view(store)
                self.assertEqual(view["tokens"]["refresh_token"], PLACEHOLDER)
                self.assertNotIn(self.token, json.dumps(view))
            else:
                with self.assertRaises(CredentialError):
                    login_view(store)

    def test_claude_and_opencode_legacy_and_v2_logins(self):
        self.write(
            ".credentials.json",
            {
                "claudeAiOauth": {
                    "accessToken": self.token,
                    "refreshToken": "refresh-fixture",
                    "expiresAt": self.future,
                }
            },
        )
        claude = CredentialStore(self.root, "claude")
        self.assertIn(self.token, claude.headers("anthropic")[0]["Authorization"])
        self.assertNotIn(self.token, json.dumps(login_view(claude)))
        self.write("auth.json", {"openai": {"type": "api", "key": self.token}})
        store = CredentialStore(self.root, "opencode")
        self.assertEqual(login_view(store)["openai"]["key"], PLACEHOLDER)
        (self.root / "auth.json").unlink()
        self.write(
            "brig-export.json",
            [
                None,
                {"integrationID": "openai", "active": False},
                {
                    "integrationID": "openai",
                    "active": True,
                    "value": {
                        "type": "oauth",
                        "access": self.token,
                        "refresh": "refresh-fixture",
                        "expires": self.future,
                        "metadata": {"accountID": "account-fixture"},
                    },
                },
            ],
        )
        self.assertEqual(
            store.headers("openai")[0]["ChatGPT-Account-Id"], "account-fixture"
        )
        self.assertEqual(login_view(store)["openai"]["type"], "oauth")
        self.assertNotIn(self.token, json.dumps(login_view(store)))

    def test_missing_and_invalid_credentials_fail_closed(self):
        for agent, provider in (
            ("codex", "openai"),
            ("claude", "anthropic"),
            ("opencode", "google"),
        ):
            with self.assertRaises(CredentialError):
                CredentialStore(self.root, agent).headers(provider)
        for expires, account in (
            ("never", None),
            (self.future, "bad\naccount"),
            (self.future, 7),
        ):
            self.write(
                "brig-auth.json",
                {
                    "openai": {
                        "type": "oauth",
                        "access": self.token,
                        "expires": expires,
                        "accountId": account,
                    }
                },
            )
            with self.assertRaises(CredentialError):
                CredentialStore(self.root, "codex").headers("openai")
        self.assertEqual(
            login_view(CredentialStore(self.root, "opencode"))["openai"]["access"],
            placeholder_jwt(),
        )

    def test_oauth_renewal_persists_each_native_format(self):
        fixtures = (
            (
                "codex",
                "openai",
                "auth.json",
                {
                    "tokens": {
                        "access_token": self.token,
                        "refresh_token": "refresh-fixture",
                        "account_id": "account-fixture",
                    }
                },
            ),
            (
                "claude",
                "anthropic",
                ".credentials.json",
                {
                    "claudeAiOauth": {
                        "accessToken": self.token,
                        "refreshToken": "refresh-fixture",
                        "expiresAt": 0,
                    }
                },
            ),
            (
                "opencode",
                "openai",
                "auth.json",
                {
                    "openai": {
                        "type": "oauth",
                        "access": self.token,
                        "refresh": "refresh-fixture",
                        "expires": 0,
                    }
                },
            ),
            (
                "opencode",
                "openai",
                "brig-auth.json",
                {
                    "openai": {
                        "type": "oauth",
                        "access": self.token,
                        "refresh": "refresh-fixture",
                        "expires": 0,
                    }
                },
            ),
            (
                "opencode",
                "openai",
                "brig-export.json",
                [
                    {
                        "integrationID": "openai",
                        "active": True,
                        "value": {
                            "type": "oauth",
                            "access": self.token,
                            "refresh": "refresh-fixture",
                            "expires": 0,
                        },
                    }
                ],
            ),
        )
        for agent, provider, name, raw in fixtures:
            for path in self.root.glob("*.json"):
                path.unlink()
            path = self.write(name, raw)
            update = {
                "access_token": placeholder_jwt(),
                "refresh_token": "new-refresh-fixture",
                "id_token": "id-token-fixture",
                "expires_in": 3600,
            }
            with patch(
                "brig.auth_proxy.credentials.refresh", return_value=update
            ) as renewal:
                headers, secrets = CredentialStore(self.root, agent).headers(provider)
            renewal.assert_called_once_with(provider, "refresh-fixture")
            self.assertIn(update["access_token"], headers["Authorization"])
            self.assertIn(self.token, secrets)
            self.assertIn(update["access_token"], path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_renewal_and_disk_failure_do_not_publish_new_token(self):
        path = self.write(
            "brig-auth.json",
            {
                "openai": {
                    "type": "oauth",
                    "access": self.token,
                    "refresh": "refresh-fixture",
                    "expires": 0,
                }
            },
        )
        original = path.read_bytes()
        for lifetime in ("bad", True, 0, 31536001):
            with (
                patch(
                    "brig.auth_proxy.credentials.refresh",
                    return_value={
                        "access_token": "new-token-fixture",
                        "expires_in": lifetime,
                    },
                ),
                self.assertRaises(CredentialError),
            ):
                CredentialStore(self.root, "codex").headers("openai")
            self.assertEqual(path.read_bytes(), original)
        with (
            patch(
                "brig.auth_proxy.credentials.refresh",
                return_value={"access_token": "new-token-fixture"},
            ),
            patch("brig.auth_proxy.storage.os.replace", side_effect=OSError),
            self.assertRaises(CredentialError),
        ):
            CredentialStore(self.root, "codex").headers("openai")
        self.assertEqual(path.read_bytes(), original)

    def test_host_key_management_switches_to_native_login_without_deleting_other_keys(
        self,
    ):
        from brig.auth_proxy.maintenance import clear_override, set_api_key

        set_api_key(self.root, "openai", self.token)
        set_api_key(self.root, "google", "other-provider-fixture")
        self.write("auth.json", {"OPENAI_API_KEY": "native-provider-fixture"})
        clear_override(self.root, "codex")
        self.assertNotIn("openai", read_json(self.root / "brig-auth.json"))
        self.assertIn("google", read_json(self.root / "brig-auth.json"))
        clear_override(self.root, "codex")
        self.write(".credentials.json", {"claudeAiOauth": {"accessToken": self.token}})
        clear_override(self.root, "claude")
        self.write("brig-auth.json", [1])
        with self.assertRaises(CredentialError):
            set_api_key(self.root, "openai", self.token)

    def test_refresh_is_bounded_does_not_follow_redirects_or_echo_errors(self):
        opener = MagicMock()
        for response in (b"[]", b"{}", b"x" * (1024 * 1024 + 1), b"{bad"):
            opener.open.return_value.__enter__.return_value.read.return_value = response
            with (
                patch(
                    "brig.auth_proxy.credentials.urllib.request.build_opener",
                    return_value=opener,
                ),
                self.assertRaises(CredentialError),
            ):
                refresh("openai", "refresh-fixture")
        opener.open.side_effect = OSError(self.token)
        with (
            patch(
                "brig.auth_proxy.credentials.urllib.request.build_opener",
                return_value=opener,
            ),
            self.assertRaises(CredentialError) as error,
        ):
            refresh("anthropic", "refresh-fixture")
        self.assertNotIn(self.token, str(error.exception))
        opener.open.side_effect = None
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"access_token": self.token}
        ).encode()
        with patch(
            "brig.auth_proxy.credentials.urllib.request.build_opener",
            return_value=opener,
        ):
            self.assertEqual(
                refresh("openai", "refresh-fixture")["access_token"], self.token
            )
        with self.assertRaises(CredentialError):
            NoRedirect().redirect_request(
                None, None, 302, "", {}, "https://evil.example"
            )
