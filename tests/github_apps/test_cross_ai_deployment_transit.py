from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.github_apps.cross_ai_deployment_policy.dsse import verify_json_envelope
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.github import HTTPResponse
from scripts.github_apps.cross_ai_deployment_policy.transit import VaultTransitSigner


class TransitTransport:
    def __init__(self, key: Ed25519PrivateKey, version: int = 3) -> None:
        self.key = key
        self.version = version
        self.calls = []

    def request(self, method, url, *, headers, body=None, timeout=10.0):
        self.calls.append((method, url, dict(headers), body))
        request = json.loads(body)
        message = base64.b64decode(request["input"], validate=True)
        signature = self.key.sign(message)
        return HTTPResponse(
            200,
            {},
            json.dumps(
                {
                    "data": {
                        "signature": (
                            f"vault:v{self.version}:"
                            + base64.b64encode(signature).decode()
                        )
                    }
                }
            ).encode(),
        )


class VaultTransitSignerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.token = Path(self.directory.name) / "token"
        self.token.write_text("hvs." + ("a" * 40), encoding="ascii")
        self.token.chmod(0o600)
        self.key = Ed25519PrivateKey.from_private_bytes(b"\x08" * 32)
        self.transport = TransitTransport(self.key)
        self.signer = VaultTransitSigner(
            vault_origin="https://vault.example.test",
            token_file=self.token,
            mount="cross-ai",
            key_name="anthropic",
            key_version=3,
            transport=self.transport,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_signs_dsse_with_version_bound_transit_identity(self) -> None:
        payload = {"subject": "sha256:" + ("a" * 64), "verdict": "AGREE"}
        envelope = self.signer.sign_json_envelope(
            payload_type="application/vnd.test+json",
            payload=payload,
        )
        verified = verify_json_envelope(
            envelope,
            expected_payload_type="application/vnd.test+json",
            allowed_keys={
                "vault-transit://cross-ai/anthropic#v3": self.key.public_key().public_bytes_raw()
            },
        )
        self.assertEqual(verified.payload, payload)
        call = self.transport.calls[0]
        self.assertEqual(call[1], "https://vault.example.test/v1/cross-ai/sign/anthropic")
        self.assertEqual(call[2]["X-Vault-Token"], "hvs." + ("a" * 40))
        self.assertNotIn(("hvs." + ("a" * 40)).encode(), call[3])

    def test_rejects_unexpected_key_version_and_insecure_origin(self) -> None:
        self.transport.version = 4
        with self.assertRaisesRegex(PolicyError, "VAULT_SIGN_VERSION_MISMATCH"):
            self.signer.sign(b"message")
        with self.assertRaisesRegex(PolicyError, "VAULT_ORIGIN_INVALID"):
            VaultTransitSigner(
                vault_origin="http://vault.example.test",
                token_file=self.token,
                mount="cross-ai",
                key_name="anthropic",
                key_version=3,
            )

    def test_rejects_symlink_and_group_readable_token_files(self) -> None:
        linked = Path(self.directory.name) / "linked-token"
        linked.symlink_to(self.token)
        with self.assertRaisesRegex(PolicyError, "VAULT_TOKEN_UNAVAILABLE"):
            VaultTransitSigner(
                vault_origin="https://vault.example.test",
                token_file=linked,
                mount="cross-ai",
                key_name="openai",
                key_version=3,
            )

        self.token.chmod(0o640)
        with self.assertRaisesRegex(PolicyError, "VAULT_TOKEN_FILE_INVALID"):
            VaultTransitSigner(
                vault_origin="https://vault.example.test",
                token_file=self.token,
                mount="cross-ai",
                key_name="openai",
                key_version=3,
            )


if __name__ == "__main__":
    unittest.main()
