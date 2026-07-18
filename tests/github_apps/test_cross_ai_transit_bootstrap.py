from __future__ import annotations

import argparse
import base64
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ops/bootstrap_cross_ai_transit.py"
SPEC = importlib.util.spec_from_file_location("cross_ai_transit_bootstrap", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load Transit bootstrap module")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeVaultClient:
    instances: list["FakeVaultClient"] = []
    unsafe_key = False
    existing = False
    root_policies = ["root"]
    sealed = False
    wrong_mount_type = False

    def __init__(self, *, origin: str, token: str) -> None:
        self.origin = origin
        self.token = token
        self.calls: list[tuple[str, str, object]] = []
        self.mount_exists = type(self).existing
        self.keys: dict[str, dict[str, object]] = {}
        self.policy: str | None = "already" if type(self).existing else None
        if type(self).existing:
            for index, name in enumerate(MODULE.KEY_NAMES, start=1):
                self.keys[name] = self._key(name, index)
        type(self).instances.append(self)

    @staticmethod
    def _response(status: int, payload=None):
        return MODULE.VaultResponse(status=status, payload=payload)

    @classmethod
    def _key(cls, name: str, index: int) -> dict[str, object]:
        return {
            "type": "ed25519",
            "derived": False,
            "exportable": cls.unsafe_key and name == "anthropic",
            "allow_plaintext_backup": False,
            "deletion_allowed": False,
            "supports_signing": True,
            "latest_version": 1,
            "keys": {
                "1": {
                    "public_key": base64.b64encode(bytes([index]) * 32).decode("ascii")
                }
            },
        }

    def request(self, method, path, payload=None, *, expected=frozenset({200, 204})):
        self.calls.append((method, path, payload))
        if path == "sys/health":
            return self._response(
                200,
                {
                    "initialized": True,
                    "sealed": type(self).sealed,
                    "standby": False,
                    "cluster_id": "test-cluster-id",
                    "cluster_name": "vault-test",
                },
            )
        if path == "auth/token/lookup-self":
            return self._response(200, {"data": {"policies": type(self).root_policies}})
        if path == "sys/auth":
            return self._response(200, {"data": {"approle/": {"type": "approle"}}})
        if path == "sys/mounts":
            mount_type = "kv" if type(self).wrong_mount_type else "transit"
            data = {"cross-ai/": {"type": mount_type}} if self.mount_exists else {}
            return self._response(200, {"data": data})
        if path == "sys/mounts/cross-ai" and method == "POST":
            self.mount_exists = True
            return self._response(204)
        if path.startswith("cross-ai/keys/"):
            name = path.rsplit("/", 1)[1]
            if method == "GET":
                if name not in self.keys:
                    return self._response(404, {"errors": ["missing"]})
                return self._response(200, {"data": self.keys[name]})
            self.keys[name] = self._key(name, MODULE.KEY_NAMES.index(name) + 1)
            return self._response(204)
        if path == "sys/policies/acl/vault-config-reconciler":
            if method == "GET":
                if self.policy is None:
                    return self._response(404, {"errors": ["missing"]})
                return self._response(200, {"data": {"policy": self.policy}})
            self.policy = payload["policy"]
            return self._response(204)
        raise AssertionError(f"unexpected request {method} {path}")


class TransitBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeVaultClient.instances.clear()
        FakeVaultClient.unsafe_key = False
        FakeVaultClient.existing = False
        FakeVaultClient.root_policies = ["root"]
        FakeVaultClient.sealed = False
        FakeVaultClient.wrong_mount_type = False
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.token = self.root / "root-token"
        self.test_token = "unit-test-" + ("x" * 24)
        self.token.write_text(self.test_token + "\n", encoding="ascii")
        self.token.chmod(0o600)
        self.policy = self.root / "reconciler.hcl"
        self.policy.write_text('path "sys/mounts" { capabilities = ["read"] }\n')

    def tearDown(self) -> None:
        self.directory.cleanup()

    def args(self) -> argparse.Namespace:
        return argparse.Namespace(
            vault_addr="http://127.0.0.1:8201",
            root_token_file=self.token,
            expected_cluster_id="test-cluster-id",
            reconciler_policy=self.policy,
            receipt_out=self.root / "receipt.json",
        )

    def test_creates_exact_mount_keys_and_public_receipt_without_secret(self) -> None:
        with patch.object(MODULE, "VaultClient", FakeVaultClient):
            receipt = MODULE.bootstrap(self.args())
        client = FakeVaultClient.instances[-1]
        self.assertEqual(
            receipt["schemaVersion"],
            "acik.cross-ai-transit-bootstrap-receipt.v2",
        )
        self.assertEqual(receipt["scope"], "test-only")
        self.assertEqual(len(receipt["keys"]), 6)
        self.assertEqual(
            {item["keyName"] for item in receipt["keys"]}, set(MODULE.KEY_NAMES)
        )
        self.assertIn("mount:cross-ai", receipt["createdResources"])
        self.assertIn("policy:vault-config-reconciler", receipt["updatedResources"])
        for item in receipt["keys"]:
            self.assertEqual(item["keyType"], "ed25519")
            self.assertIs(item["derived"], False)
            self.assertIs(item["exportable"], False)
            self.assertIs(item["allowPlaintextBackup"], False)
            self.assertIs(item["deletionAllowed"], False)
            self.assertIs(item["supportsSigning"], True)
            self.assertEqual(
                item["versionHistory"],
                [
                    {
                        "version": item["keyVersion"],
                        "publicKeyBase64": item["publicKeyBase64"],
                    }
                ],
            )
        serialized = str(receipt)
        self.assertNotIn(self.test_token, serialized)
        mount_create = next(
            call for call in client.calls if call[1] == "sys/mounts/cross-ai"
        )
        self.assertEqual(mount_create[2]["type"], "transit")
        for name in MODULE.KEY_NAMES:
            create = next(
                call
                for call in client.calls
                if call[0] == "POST" and call[1] == f"cross-ai/keys/{name}"
            )
            self.assertEqual(
                create[2],
                {
                    "type": "ed25519",
                    "derived": False,
                    "exportable": False,
                    "allow_plaintext_backup": False,
                },
            )

    def test_existing_safe_resources_are_verified_without_recreation(self) -> None:
        FakeVaultClient.existing = True

        class ExistingClient(FakeVaultClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.policy = self_outer.policy.read_text()

        self_outer = self
        with patch.object(MODULE, "VaultClient", ExistingClient):
            receipt = MODULE.bootstrap(self.args())
        self.assertEqual(receipt["createdResources"], [])
        self.assertEqual(receipt["updatedResources"], [])
        client = ExistingClient.instances[-1]
        self.assertFalse(
            any(call[0] == "POST" and "/keys/" in call[1] for call in client.calls)
        )

    def test_rejects_existing_exportable_key_and_wrong_cluster(self) -> None:
        FakeVaultClient.existing = True
        FakeVaultClient.unsafe_key = True
        with patch.object(MODULE, "VaultClient", FakeVaultClient):
            with self.assertRaisesRegex(MODULE.BootstrapError, "unsafe immutable"):
                MODULE.bootstrap(self.args())
        FakeVaultClient.unsafe_key = False
        args = self.args()
        args.expected_cluster_id = "another-cluster"
        with patch.object(MODULE, "VaultClient", FakeVaultClient):
            with self.assertRaisesRegex(MODULE.BootstrapError, "cluster ID"):
                MODULE.bootstrap(args)

    def test_rejects_incomplete_public_key_history(self) -> None:
        FakeVaultClient.existing = True

        class MissingHistoryClient(FakeVaultClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                anthropic = self.keys["anthropic"]
                anthropic["latest_version"] = 2

        with patch.object(MODULE, "VaultClient", MissingHistoryClient):
            with self.assertRaisesRegex(MODULE.BootstrapError, "history is incomplete"):
                MODULE.bootstrap(self.args())

    def test_rejects_non_root_sealed_vault_and_mount_type_collision(self) -> None:
        FakeVaultClient.root_policies = ["default", "operator"]
        with patch.object(MODULE, "VaultClient", FakeVaultClient):
            with self.assertRaisesRegex(MODULE.BootstrapError, "root token"):
                MODULE.bootstrap(self.args())
        FakeVaultClient.root_policies = ["root"]
        FakeVaultClient.sealed = True
        with patch.object(MODULE, "VaultClient", FakeVaultClient):
            with self.assertRaisesRegex(
                MODULE.BootstrapError, "initialized and unsealed"
            ):
                MODULE.bootstrap(self.args())
        FakeVaultClient.sealed = False
        FakeVaultClient.existing = True
        FakeVaultClient.wrong_mount_type = True
        with patch.object(MODULE, "VaultClient", FakeVaultClient):
            with self.assertRaisesRegex(MODULE.BootstrapError, "non-Transit"):
                MODULE.bootstrap(self.args())

    def test_receipt_writer_never_overwrites_existing_path(self) -> None:
        output = self.root / "receipt.json"
        MODULE._write_exclusive(output, {"public": True})
        self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(MODULE.BootstrapError, "new secure file"):
            MODULE._write_exclusive(output, {"public": False})

    def test_root_token_file_rejects_weak_mode_and_symlink(self) -> None:
        self.token.chmod(0o644)
        with self.assertRaisesRegex(MODULE.BootstrapError, "group/world"):
            MODULE._secure_token_file(self.token)
        self.token.chmod(0o600)
        link = self.root / "token-link"
        link.symlink_to(self.token)
        with self.assertRaisesRegex(MODULE.BootstrapError, "unavailable"):
            MODULE._secure_token_file(link)

    def test_policy_sources_are_sign_only_and_revocation_emission_is_denied(
        self,
    ) -> None:
        policy_dir = ROOT / "bootstrap/vault-policies/test"
        for path in sorted(policy_dir.glob("cross-ai-*.hcl")):
            text = path.read_text(encoding="utf-8")
            allowed_blocks = [
                block
                for block in text.split("}")
                if "capabilities" in block and '"deny"' not in block
            ]
            self.assertEqual(len(allowed_blocks), 1, path)
            self.assertIn('path "cross-ai/sign/', allowed_blocks[0])
            self.assertIn('capabilities = ["update"]', allowed_blocks[0])
            self.assertNotIn("exportable", allowed_blocks[0])
            for denied in (
                "keys",
                "export",
                "backup",
                "restore",
                "datakey",
                "encrypt",
                "decrypt",
                "rewrap",
                "hmac",
            ):
                self.assertIn(
                    f'path "cross-ai/{denied}/*" {{\n  capabilities = ["deny"]',
                    text,
                    path,
                )

        reconciler = (ROOT / "scripts/ops/vault-policy-reconcile.sh").read_text()
        self.assertIn("APPLY_FAIL=0", reconciler)
        self.assertIn("APPLY_FAIL=1", reconciler)
        self.assertIn("manifest policy file missing", reconciler)
        self.assertIn("one or more Vault policy/AppRole writes failed", reconciler)
        self.assertIn("AppRole role-id retrieval failed", reconciler)
        self.assertIn("AppRole secret-id emission failed", reconciler)
        emission_manifest = reconciler.split("EMITTABLE_APPROLES=(", 1)[1].split(
            ")", 1
        )[0]
        self.assertNotIn("cross-ai-revocation-test", emission_manifest)
        self.assertNotIn("cross-ai-issuer-anthropic-test", emission_manifest)
        self.assertNotIn("cross-ai-issuer-minimax-test", emission_manifest)
        self.assertNotIn("cross-ai-issuer-openai-test", emission_manifest)
        self.assertNotIn("cross-ai-coordinator-test", emission_manifest)
        self.assertIn("secret-id emission is not permitted", reconciler)
        self.assertIn("backup|restore|datakey", reconciler)
        self.assertIn("rewrap|hmac", reconciler)
        exact_paths = {
            "cross-ai-issuer-anthropic-test": "cross-ai/sign/anthropic",
            "cross-ai-issuer-minimax-test": "cross-ai/sign/minimax",
            "cross-ai-issuer-openai-test": "cross-ai/sign/openai",
            "cross-ai-coordinator-test": "cross-ai/sign/coordinator",
            "cross-ai-revocation-test": "cross-ai/sign/revocation",
            "cross-ai-runner-management-test": "cross-ai/sign/runner-management",
        }
        for policy_name, sign_path in exact_paths.items():
            self.assertIn(
                f'{policy_name}) expected_sign_path="{sign_path}"',
                reconciler,
            )
        config_policy = (policy_dir / "vault-config-reconciler.hcl").read_text(
            encoding="utf-8"
        )
        routine_approles = reconciler.split("APPROLES=(", 1)[1].split(")", 1)[0]
        self.assertNotIn(
            'path "auth/approle/role/cross-ai-revocation-test/secret-id"',
            config_policy,
        )
        for role in (
            "cross-ai-issuer-anthropic-test",
            "cross-ai-issuer-minimax-test",
            "cross-ai-issuer-openai-test",
            "cross-ai-coordinator-test",
        ):
            for suffix in ("", "/role-id", "/secret-id"):
                self.assertNotIn(
                    f'path "auth/approle/role/{role}{suffix}"',
                    config_policy,
                )
            self.assertNotIn(f'"{role}|', routine_approles)
        self.assertNotRegex(
            reconciler,
            r"cross-ai-(?:issuer-[a-z]+|coordinator)-test\|[^\n]*token_num_uses=0",
        )


if __name__ == "__main__":
    unittest.main()
