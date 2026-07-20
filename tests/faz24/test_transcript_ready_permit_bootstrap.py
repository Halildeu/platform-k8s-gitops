from __future__ import annotations

import base64
import datetime as dt
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts/ops"
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

import bootstrap_faz24_transcript_ready_permit_transit as bootstrap  # noqa: E402

NOW = dt.datetime(2026, 7, 20, 8, 0, tzinfo=dt.timezone.utc)
ORIGIN = "https://vault.test.example"
CLUSTER_ID = "test-cluster-1"
ROOT_TOKEN = "hvs." + ("r" * 40)
SIGNER_TOKEN = "hvs." + ("s" * 40)
ACCESSOR = "accessor-" + ("a" * 32)
PUBLIC_KEY = base64.b64encode(b"\x05" * 32).decode("ascii")


class FakeVaultClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.mount_exists = False
        self.key_exists = False
        self.policy: str | None = None
        self.lookup_override: dict[str, Any] = {}
        self.lookup_payload_valid = True
        self.revoked = False

    def response(self, status: int, payload: dict[str, Any] | None):
        return bootstrap.VaultResponse(status, payload)

    def key_data(self) -> dict[str, Any]:
        return {
            "type": "ed25519",
            "derived": False,
            "exportable": False,
            "allow_plaintext_backup": False,
            "deletion_allowed": False,
            "supports_signing": True,
            "latest_version": 1,
            "keys": {"1": {"public_key": PUBLIC_KEY}},
        }

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expected: frozenset[int] = frozenset({200, 204}),
    ):
        del expected
        self.calls.append((method, path, payload))
        if (method, path) == ("GET", "sys/health"):
            return self.response(
                200,
                {
                    "initialized": True,
                    "sealed": False,
                    "standby": False,
                    "cluster_id": CLUSTER_ID,
                },
            )
        if (method, path) == ("GET", "auth/token/lookup-self"):
            return self.response(200, {"data": {"policies": ["root"]}})
        if (method, path) == ("GET", "sys/mounts"):
            mounts = (
                {f"{bootstrap.MOUNT}/": {"type": "transit"}}
                if self.mount_exists
                else {}
            )
            return self.response(200, {"data": mounts})
        if (method, path) == ("POST", f"sys/mounts/{bootstrap.MOUNT}"):
            self.mount_exists = True
            return self.response(204, None)
        if (method, path) == (
            "GET",
            f"{bootstrap.MOUNT}/keys/{bootstrap.KEY_NAME}",
        ):
            if not self.key_exists:
                return self.response(404, None)
            return self.response(200, {"data": self.key_data()})
        if (method, path) == (
            "POST",
            f"{bootstrap.MOUNT}/keys/{bootstrap.KEY_NAME}",
        ):
            self.key_exists = True
            return self.response(204, None)
        if method == "GET" and path == f"sys/policies/acl/{bootstrap.POLICY_NAME}":
            if self.policy is None:
                return self.response(404, None)
            return self.response(200, {"data": {"policy": self.policy}})
        if method == "PUT" and path == f"sys/policies/acl/{bootstrap.POLICY_NAME}":
            assert payload is not None
            self.policy = payload["policy"]
            return self.response(204, None)
        if (method, path) == ("POST", "auth/token/create"):
            return self.response(
                200,
                {
                    "auth": {
                        "client_token": SIGNER_TOKEN,
                        "accessor": ACCESSOR,
                        "token_policies": [bootstrap.POLICY_NAME],
                        "lease_duration": bootstrap.SIGNER_TTL_SECONDS,
                        "renewable": False,
                    }
                },
            )
        if (method, path) == ("POST", "auth/token/lookup-accessor"):
            lookup = {
                "policies": [bootstrap.POLICY_NAME],
                "renewable": False,
                "num_uses": bootstrap.SIGNER_TOKEN_USES,
                "ttl": bootstrap.SIGNER_TTL_SECONDS - 1,
            }
            lookup.update(self.lookup_override)
            return self.response(200, {"data": lookup} if self.lookup_payload_valid else {})
        if (method, path) == ("POST", "auth/token/revoke-accessor"):
            self.revoked = True
            return self.response(204, None)
        raise AssertionError(f"unexpected Vault call: {method} {path}")


class TranscriptReadyPermitBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        self.signer_token = self.root / "signer.token"
        self.receipt = self.root / "receipt.json"
        self.client = FakeVaultClient()

    def run_bootstrap(self) -> dict[str, Any]:
        return bootstrap.bootstrap(
            client=self.client,
            vault_origin=ORIGIN,
            expected_cluster_id=CLUSTER_ID,
            signer_token_out=self.signer_token,
            receipt_out=self.receipt,
            now=NOW,
        )

    def test_full_bootstrap_mints_narrow_token_and_public_receipt(self) -> None:
        receipt = self.run_bootstrap()

        self.assertEqual(SIGNER_TOKEN, self.signer_token.read_text(encoding="ascii"))
        self.assertEqual(receipt, json.loads(self.receipt.read_bytes()))
        self.assertEqual(0o600, stat.S_IMODE(self.signer_token.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.receipt.stat().st_mode))
        self.assertNotIn(SIGNER_TOKEN.encode(), self.receipt.read_bytes())
        self.assertNotIn(ROOT_TOKEN.encode(), self.receipt.read_bytes())
        self.assertEqual(
            "vault-transit://meeting-ai/transcript-ready-permit#v1",
            receipt["keyId"],
        )
        create_payload = next(
            payload
            for method, path, payload in self.client.calls
            if (method, path) == ("POST", "auth/token/create")
        )
        self.assertEqual(
            {
                "policies": [bootstrap.POLICY_NAME],
                "ttl": "1800s",
                "explicit_max_ttl": "1800s",
                "renewable": False,
                "num_uses": 1,
                "no_default_policy": True,
            },
            create_payload,
        )
        self.assertFalse(self.client.revoked)

    def test_token_readback_mismatch_revokes_without_writing_outputs(self) -> None:
        self.client.lookup_override = {"num_uses": 9}

        with self.assertRaisesRegex(bootstrap.BootstrapError, "readback"):
            self.run_bootstrap()

        self.assertTrue(self.client.revoked)
        self.assertFalse(self.signer_token.exists())
        self.assertFalse(self.receipt.exists())

    def test_token_readback_failure_revokes_without_writing_outputs(self) -> None:
        self.client.lookup_payload_valid = False

        with self.assertRaisesRegex(bootstrap.BootstrapError, "response data"):
            self.run_bootstrap()

        self.assertTrue(self.client.revoked)
        self.assertFalse(self.signer_token.exists())
        self.assertFalse(self.receipt.exists())

    def test_existing_output_is_preserved_and_minted_token_is_revoked(self) -> None:
        original = b"operator-owned-existing-receipt"
        self.receipt.write_bytes(original)

        with self.assertRaisesRegex(bootstrap.BootstrapError, "new file"):
            self.run_bootstrap()

        self.assertTrue(self.client.revoked)
        self.assertEqual(original, self.receipt.read_bytes())
        self.assertFalse(self.signer_token.exists())

    def test_policy_file_must_match_embedded_reviewed_contract(self) -> None:
        altered = self.root / "altered-policy.hcl"
        altered.write_text("path \"secret/*\" { capabilities = [\"read\"] }\n")

        with mock.patch.object(bootstrap, "POLICY_PATH", altered):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "differs"):
                self.run_bootstrap()

        self.assertFalse(
            any(path == "auth/token/create" for _, path, _ in self.client.calls)
        )

    def test_unsafe_existing_key_is_rejected_before_token_mint(self) -> None:
        self.client.key_exists = True
        original_key_data = self.client.key_data

        def unsafe_key_data() -> dict[str, Any]:
            data = original_key_data()
            data["exportable"] = True
            return data

        self.client.key_data = unsafe_key_data  # type: ignore[method-assign]

        with self.assertRaisesRegex(bootstrap.BootstrapError, "safety properties"):
            self.run_bootstrap()

        self.assertFalse(
            any(path == "auth/token/create" for _, path, _ in self.client.calls)
        )

    def test_secure_token_requires_owner_only_ascii_regular_file(self) -> None:
        token_path = self.root / "root.token"
        token_path.write_text(ROOT_TOKEN, encoding="ascii")
        token_path.chmod(0o600)
        self.assertEqual(ROOT_TOKEN, bootstrap.secure_token(token_path, "root"))

        token_path.chmod(0o644)
        with self.assertRaisesRegex(bootstrap.BootstrapError, "owner-only"):
            bootstrap.secure_token(token_path, "root")

    def test_strict_json_rejects_duplicates_floats_and_constants(self) -> None:
        for raw in (b'{"a":1,"a":2}', b'{"a":1.5}', b'{"a":NaN}'):
            with self.subTest(raw=raw):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.json_object(raw, "fixture")

    def test_canonical_https_origin_rejects_noncanonical_values(self) -> None:
        self.assertEqual(ORIGIN, bootstrap.canonical_https_origin(ORIGIN + "/"))
        for value in (
            "http://vault.test.example",
            "https://user@vault.test.example",
            "https://vault.test.example/v1",
            "https://vault.test.example?token=x",
        ):
            with self.subTest(value=value):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.canonical_https_origin(value)

    def test_write_exclusive_rejects_group_writable_parent(self) -> None:
        output_dir = self.root / "shared"
        output_dir.mkdir(mode=0o770)
        output_dir.chmod(0o770)

        with self.assertRaisesRegex(bootstrap.BootstrapError, "owner controlled"):
            bootstrap.write_exclusive(output_dir / "token", b"secret", 0o600)

        self.assertFalse((output_dir / "token").exists())


if __name__ == "__main__":
    unittest.main()
