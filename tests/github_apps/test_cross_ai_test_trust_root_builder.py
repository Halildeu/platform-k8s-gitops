from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ops/build_cross_ai_test_trust_root.py"
SPEC = importlib.util.spec_from_file_location("cross_ai_test_trust_root", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load TEST trust-root builder")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


TRUST_ROOT_ID = "10000000-0000-4000-8000-000000000099"
ISSUED_AT = "2026-07-18T18:00:00Z"
EXPIRES_AT = "2026-08-17T18:00:00Z"
ISSUER_IMAGE_DIGEST = "sha256:" + ("b" * 64)
LAUNCHER_SOURCE_SHA256 = "sha256:" + ("c" * 64)
CONTAINER_ARGS_SHA256 = "sha256:" + ("d" * 64)


def public_key(seed: int) -> str:
    return base64.b64encode(bytes([seed]) * 32).decode("ascii")


def receipt() -> dict[str, object]:
    keys: list[dict[str, object]] = []
    for index, name in enumerate(MODULE.EXPECTED_KEY_NAMES, start=1):
        encoded = public_key(index)
        keys.append(
            {
                "keyId": f"vault-transit://cross-ai/{name}#v1",
                "keyName": name,
                "keyVersion": 1,
                "publicKeyBase64": encoded,
                "keyType": "ed25519",
                "derived": False,
                "exportable": False,
                "allowPlaintextBackup": False,
                "deletionAllowed": False,
                "supportsSigning": True,
                "versionHistory": [
                    {"version": 1, "publicKeyBase64": encoded}
                ],
            }
        )
    return {
        "schemaVersion": "acik.cross-ai-transit-bootstrap-receipt.v2",
        "scope": "test-only",
        "vaultOrigin": "https://vault-test.example.invalid",
        "vaultClusterId": "test-cluster-id",
        "vaultClusterName": "vault-test",
        "mount": "cross-ai",
        "keys": keys,
        "reconcilerPolicyName": "vault-config-reconciler",
        "reconcilerPolicySha256": "sha256:" + ("a" * 64),
        "createdResources": ["key:anthropic"],
        "updatedResources": ["policy:vault-config-reconciler"],
        "verifiedAbsentResources": [
            "approle:cross-ai-issuer-anthropic-test",
            "policy:cross-ai-issuer-anthropic-test",
            "approle:cross-ai-issuer-minimax-test",
            "policy:cross-ai-issuer-minimax-test",
        ],
        "verifiedAt": "2026-07-18T17:59:00Z",
        "requiresOutOfBandOwnerPin": True,
    }


def build(
    value: dict[str, object],
    *,
    trust_root_id: str = TRUST_ROOT_ID,
    issued_at: str = ISSUED_AT,
    expires_at: str = EXPIRES_AT,
    previous_trust_root: dict[str, object] | None = None,
) -> dict[str, object]:
    return MODULE.build_trust_root(
        value,
        trust_root_id=trust_root_id,
        issued_at=issued_at,
        expires_at=expires_at,
        issuer_image_digest=ISSUER_IMAGE_DIGEST,
        launcher_source_sha256=LAUNCHER_SOURCE_SHA256,
        container_args_sha256=CONTAINER_ARGS_SHA256,
        attestor_api_origin="https://testai.acik.com",
        previous_trust_root=previous_trust_root,
    )


class TestTrustRootBuilderTests(unittest.TestCase):
    def test_builds_exact_provider_routes_from_public_receipt(self) -> None:
        trust_root = build(receipt())
        schema = json.loads(
            (
                ROOT / "schema/cross-ai-deployment-trust-root-v2.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            list(
                Draft202012Validator(
                    schema, format_checker=FormatChecker()
                ).iter_errors(trust_root)
            ),
            [],
        )
        self.assertEqual(
            trust_root["requiredProviderFamilies"],
            ["openai"],
        )
        self.assertEqual(len(trust_root["keys"]), 4)
        providers = {
            item["providerFamily"]: item
            for item in trust_root["keys"]
            if item["role"] == "provider-review"
        }
        self.assertEqual(set(providers), {"openai"})
        self.assertEqual(
            providers["openai"]["allowedModelIdentityClasses"],
            ["trusted-launch-attested"],
        )
        self.assertEqual(
            providers["openai"]["allowedModelIds"],
            ["gpt-5.3-codex-spark", "gpt-5.6-sol"],
        )
        serialized = MODULE._canonical_bytes(trust_root).decode("utf-8")
        for forbidden in ("token", "secretId", "credential", "privateKey"):
            self.assertNotIn(forbidden, serialized)

    def test_canonical_bytes_are_stable_and_have_a_golden_digest(self) -> None:
        first = MODULE._canonical_bytes(build(receipt()))
        second_receipt = receipt()
        second_receipt["keys"] = list(reversed(second_receipt["keys"]))
        second = MODULE._canonical_bytes(build(second_receipt))
        self.assertEqual(first, second)
        self.assertEqual(first, MODULE._canonical_bytes(json.loads(first)))
        self.assertEqual(
            hashlib.sha256(first).hexdigest(),
            "263a4578f9c79afbce553189c785411b4ac8d737fd1e7ee05e02abbcf1960a09",
        )

    def test_operational_receipt_metadata_does_not_move_public_keyset_digest(self) -> None:
        first = build(receipt())
        changed = receipt()
        changed["createdResources"] = []
        changed["updatedResources"] = []
        changed["verifiedAt"] = "2026-07-18T18:30:00Z"
        second = build(changed)
        self.assertEqual(
            first["sourcePublicKeysetSha256"],
            second["sourcePublicKeysetSha256"],
        )
        self.assertEqual(
            MODULE._canonical_bytes(first), MODULE._canonical_bytes(second)
        )

    def test_key_and_history_rotation_change_the_pinned_digest(self) -> None:
        original = build(receipt())
        rotated_receipt = receipt()
        key = rotated_receipt["keys"][0]
        rotated = public_key(21)
        key["keyVersion"] = 2
        key["keyId"] = "vault-transit://cross-ai/anthropic#v2"
        key["publicKeyBase64"] = rotated
        key["versionHistory"].append(
            {"version": 2, "publicKeyBase64": rotated}
        )
        rotated_root = build(rotated_receipt)
        self.assertNotEqual(
            original["sourcePublicKeysetSha256"],
            rotated_root["sourcePublicKeysetSha256"],
        )
        self.assertNotEqual(
            hashlib.sha256(MODULE._canonical_bytes(original)).digest(),
            hashlib.sha256(MODULE._canonical_bytes(rotated_root)).digest(),
        )

    def test_openai_rotation_emits_only_consecutive_codex_keys_with_24h_overlap(self) -> None:
        previous_root = build(receipt())
        rotated_receipt = receipt()
        key = next(
            item for item in rotated_receipt["keys"] if item["keyName"] == "openai"
        )
        rotated = public_key(22)
        key["keyVersion"] = 2
        key["keyId"] = "vault-transit://cross-ai/openai#v2"
        key["publicKeyBase64"] = rotated
        key["versionHistory"].append(
            {"version": 2, "publicKeyBase64": rotated}
        )

        trust_root = build(
            rotated_receipt,
            trust_root_id="10000000-0000-4000-8000-000000000100",
            issued_at="2026-07-21T12:34:56Z",
            expires_at="2026-07-28T12:34:56Z",
            previous_trust_root=previous_root,
        )
        providers = [
            item for item in trust_root["keys"] if item["role"] == "provider-review"
        ]
        self.assertEqual(
            [item["keyId"] for item in providers],
            [
                "vault-transit://cross-ai/openai#v1",
                "vault-transit://cross-ai/openai#v2",
            ],
        )
        previous_provider = next(
            item
            for item in previous_root["keys"]
            if item["role"] == "provider-review"
        )
        self.assertEqual(providers[0], previous_provider)
        self.assertEqual(providers[1]["notBefore"], "2026-07-21T12:34:56Z")
        for role in ("coordinator", "revocation", "runner-management"):
            self.assertEqual(
                next(item for item in trust_root["keys"] if item["role"] == role),
                next(item for item in previous_root["keys"] if item["role"] == role),
            )
        self.assertTrue(
            all(item["providerFamily"] == "openai" for item in providers)
        )

    def test_openai_rotation_rejects_missing_previous_root(self) -> None:
        rotated_receipt = receipt()
        key = next(
            item for item in rotated_receipt["keys"] if item["keyName"] == "openai"
        )
        rotated = public_key(22)
        key["keyVersion"] = 2
        key["keyId"] = "vault-transit://cross-ai/openai#v2"
        key["publicKeyBase64"] = rotated
        key["versionHistory"].append(
            {"version": 2, "publicKeyBase64": rotated}
        )
        with self.assertRaisesRegex(
            MODULE.TrustRootBuildError, "exact previous trust root"
        ):
            build(rotated_receipt)

    def test_rejects_ephemeral_and_overlong_root_lifetimes(self) -> None:
        for invalid in ("2026-07-21T18:00:00Z", "2026-08-17T18:00:01Z"):
            with self.assertRaisesRegex(
                MODULE.TrustRootBuildError, "between 168 and 720 hours"
            ):
                MODULE.build_trust_root(
                    receipt(),
                    trust_root_id=TRUST_ROOT_ID,
                    issued_at=ISSUED_AT,
                    expires_at=invalid,
                    issuer_image_digest=ISSUER_IMAGE_DIGEST,
                    launcher_source_sha256=LAUNCHER_SOURCE_SHA256,
                    container_args_sha256=CONTAINER_ARGS_SHA256,
                    attestor_api_origin="https://testai.acik.com",
                )

    def test_rejects_unknown_missing_extra_duplicate_and_swapped_keys(self) -> None:
        unknown = receipt()
        unknown["keys"][0]["keyName"] = "unknown"
        with self.assertRaisesRegex(MODULE.TrustRootBuildError, "duplicate or unknown"):
            build(unknown)

        missing = receipt()
        missing["keys"].pop()
        with self.assertRaisesRegex(MODULE.TrustRootBuildError, "exactly five"):
            build(missing)

        extra = receipt()
        extra["keys"].append(copy.deepcopy(extra["keys"][0]))
        with self.assertRaisesRegex(MODULE.TrustRootBuildError, "exactly five"):
            build(extra)

        duplicate = receipt()
        duplicate["keys"][1] = copy.deepcopy(duplicate["keys"][0])
        with self.assertRaisesRegex(MODULE.TrustRootBuildError, "duplicate or unknown"):
            build(duplicate)

        swapped = receipt()
        swapped["keys"][0]["keyId"] = "vault-transit://cross-ai/minimax#v1"
        with self.assertRaisesRegex(MODULE.TrustRootBuildError, "inconsistent"):
            build(swapped)

    def test_rejects_unsafe_settings_noncanonical_history_and_reused_key(self) -> None:
        unsafe = receipt()
        unsafe["keys"][0]["exportable"] = True
        with self.assertRaisesRegex(MODULE.TrustRootBuildError, "settings are unsafe"):
            build(unsafe)

        history = receipt()
        history["keys"][0]["versionHistory"][0]["version"] = 2
        with self.assertRaisesRegex(MODULE.TrustRootBuildError, "history is not canonical"):
            build(history)

        reused = receipt()
        reused["keys"][1]["publicKeyBase64"] = reused["keys"][0][
            "publicKeyBase64"
        ]
        reused["keys"][1]["versionHistory"][0]["publicKeyBase64"] = reused[
            "keys"
        ][0]["publicKeyBase64"]
        with self.assertRaisesRegex(
            MODULE.TrustRootBuildError, "two versions or trust roles"
        ):
            build(reused)

    def test_duplicate_json_key_and_unknown_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text(
                '{"schemaVersion":"x","schemaVersion":"y"}', encoding="utf-8"
            )
            with self.assertRaisesRegex(MODULE.TrustRootBuildError, "duplicate JSON"):
                MODULE._load_receipt(path)
        unknown = receipt()
        unknown["unexpected"] = True
        with self.assertRaisesRegex(MODULE.TrustRootBuildError, "fields are not exact"):
            build(unknown)

    def test_cli_writes_canonical_public_bytes_once_without_touching_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / "receipt.json"
            output = root / "trust-root.json"
            receipt_path.write_text(json.dumps(receipt()), encoding="utf-8")
            config_before = (
                ROOT / "config/github-apps/cross-ai-deployment-policy.example.json"
            ).read_bytes()
            argv = [
                "--receipt",
                str(receipt_path),
                "--trust-root-id",
                TRUST_ROOT_ID,
                "--issued-at",
                ISSUED_AT,
                "--expires-at",
                EXPIRES_AT,
                "--issuer-image-digest",
                ISSUER_IMAGE_DIGEST,
                "--launcher-source-sha256",
                LAUNCHER_SOURCE_SHA256,
                "--container-args-sha256",
                CONTAINER_ARGS_SHA256,
                "--attestor-api-origin",
                "https://testai.acik.com",
                "--out",
                str(output),
            ]
            self.assertEqual(MODULE.main(argv), 0)
            raw = output.read_bytes()
            self.assertEqual(raw, MODULE._canonical_bytes(json.loads(raw)))
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
            self.assertEqual(MODULE.main(argv), 2)
            self.assertEqual(
                config_before,
                (
                    ROOT
                    / "config/github-apps/cross-ai-deployment-policy.example.json"
                ).read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
