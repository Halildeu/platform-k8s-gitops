from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.github_apps.cross_ai_deployment_policy.dsse import verify_json_envelope
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.github import HTTPResponse
from scripts.github_apps.cross_ai_deployment_policy.transit import (
    VaultKubernetesTransitSigner,
    VaultTransitSigner,
)


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

    def test_rejects_token_file_owned_by_another_uid(self) -> None:
        with (
            patch(
                "scripts.github_apps.cross_ai_deployment_policy.transit.os.getuid",
                return_value=self.token.stat().st_uid + 1,
            ),
            self.assertRaisesRegex(PolicyError, "VAULT_TOKEN_FILE_INVALID"),
        ):
            VaultTransitSigner(
                vault_origin="https://vault.example.test",
                token_file=self.token,
                mount="cross-ai",
                key_name="openai",
                key_version=3,
            )


class KubernetesTransitTransport:
    def __init__(self, key: Ed25519PrivateKey) -> None:
        self.key = key
        self.calls = []

    def request(self, method, url, *, headers, body=None, timeout=10.0):
        self.calls.append((method, url, dict(headers), body))
        if url.endswith("/v1/auth/kubernetes/login"):
            return HTTPResponse(
                200,
                {},
                json.dumps(
                    {
                        "auth": {
                            "client_token": "hvs." + ("b" * 40),
                            "renewable": False,
                            "num_uses": 2,
                            "lease_duration": 300,
                            "token_policies": [
                                "cross-ai-runner-management-test"
                            ],
                        }
                    }
                ).encode(),
            )
        if url.endswith("/v1/auth/token/revoke-self"):
            return HTTPResponse(204, {}, b"")
        request = json.loads(body)
        message = base64.b64decode(request["input"], validate=True)
        signature = self.key.sign(message)
        return HTTPResponse(
            200,
            {},
            json.dumps(
                {
                    "data": {
                        "signature": "vault:v3:"
                        + base64.b64encode(signature).decode()
                    }
                }
            ).encode(),
        )


class VaultKubernetesTransitSignerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.jwt = Path(self.directory.name) / "vault-jwt"
        self.jwt.write_text("synthetic.jwt." + ("a" * 120), encoding="ascii")
        self.jwt.chmod(0o400)
        self.key = Ed25519PrivateKey.from_private_bytes(b"\x09" * 32)
        self.transport = KubernetesTransitTransport(self.key)
        self.signer = VaultKubernetesTransitSigner(
            vault_origin="https://vault.example.test",
            kubernetes_jwt_file=self.jwt,
            auth_mount="kubernetes",
            role="cross-ai-provider-review-runtime",
            expected_policy="cross-ai-runner-management-test",
            mount="cross-ai",
            key_name="runner-management",
            key_version=3,
            transport=self.transport,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_mints_one_workload_token_signs_and_revokes(self) -> None:
        envelope = self.signer.sign_json_envelope(
            payload_type="application/vnd.test+json",
            payload={"verdict": "AGREE"},
        )
        verified = verify_json_envelope(
            envelope,
            expected_payload_type="application/vnd.test+json",
            allowed_keys={
                "vault-transit://cross-ai/runner-management#v3": (
                    self.key.public_key().public_bytes_raw()
                )
            },
        )
        self.assertEqual({"verdict": "AGREE"}, verified.payload)
        self.assertEqual(
            [
                "https://vault.example.test/v1/auth/kubernetes/login",
                "https://vault.example.test/v1/cross-ai/sign/runner-management",
                "https://vault.example.test/v1/auth/token/revoke-self",
            ],
            [call[1] for call in self.transport.calls],
        )
        self.assertNotIn(
            "X-Vault-Token",
            self.transport.calls[0][2],
        )
        self.assertEqual(
            "hvs." + ("b" * 40),
            self.transport.calls[1][2]["X-Vault-Token"],
        )

    def test_rejects_unbounded_vault_policy(self) -> None:
        original = self.transport.request

        def wrong_policy(method, url, *, headers, body=None, timeout=10.0):
            if url.endswith("/v1/auth/kubernetes/login"):
                return HTTPResponse(
                    200,
                    {},
                    json.dumps(
                        {
                            "auth": {
                                "client_token": "hvs." + ("b" * 40),
                                "renewable": False,
                                "num_uses": 2,
                                "lease_duration": 300,
                                "token_policies": ["default"],
                            }
                        }
                    ).encode(),
                )
            return original(
                method,
                url,
                headers=headers,
                body=body,
                timeout=timeout,
            )

        self.transport.request = wrong_policy
        with self.assertRaisesRegex(PolicyError, "VAULT_KUBERNETES_LOGIN_INVALID"):
            self.signer.sign(b"message")


if __name__ == "__main__":
    unittest.main()
